// Persistent libcamera 0.3 capture engine for Jarvis's isolated build.
// Text commands on stdin: CAPTURE <absolute raw-file path>, QUIT.
// Responses on stdout: READY <width> <height>, OK <seconds>, ERR <reason>.
// libcamera internals may use their own threads; no camera resources are
// recreated between captures. A single request/buffer is used deliberately.
#include <libcamera/libcamera.h>
#include <libcamera/formats.h>
#include <sys/mman.h>
#include <poll.h>
#include <unistd.h>
#include <cerrno>
#include <algorithm>
#include <cstdint>
#include <chrono>
#include <condition_variable>
#include <cstring>
#include <fstream>
#include <iostream>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <vector>

using namespace libcamera;
using Clock = std::chrono::steady_clock;

static void check(int status, const char *where) {
    if (status < 0)
        throw std::runtime_error(std::string(where) + ": " + std::to_string(status));
}

class CameraEngine {
public:
    CameraEngine() {
        check(manager_.start(), "CameraManager.start");
        if (manager_.cameras().empty())
            throw std::runtime_error("No libcamera devices");
        camera_ = manager_.cameras()[0];
        check(camera_->acquire(), "Camera.acquire");
        config_ = camera_->generateConfiguration({StreamRole::StillCapture});
        if (!config_ || config_->empty())
            throw std::runtime_error("Unable to configure still stream");
        auto &cfg = config_->at(0);
        cfg.size.width = 1280;
        cfg.size.height = 960;
        cfg.pixelFormat = formats::RGB888;
        if (config_->validate() == CameraConfiguration::Invalid ||
            cfg.size.width != 1280 || cfg.size.height != 960 ||
            cfg.pixelFormat != formats::RGB888)
            throw std::runtime_error("1280x960 RGB888 unavailable");
        check(camera_->configure(config_.get()), "Camera.configure");
        width_ = cfg.size.width;
        height_ = cfg.size.height;
        stride_ = cfg.stride;
        if (stride_ < width_ * 3)
            throw std::runtime_error("Unexpected RGB frame stride");
        stream_ = cfg.stream();
        allocator_ = std::make_unique<FrameBufferAllocator>(camera_);
        check(allocator_->allocate(stream_), "FrameBufferAllocator.allocate");
        const auto &buffers = allocator_->buffers(stream_);
        if (buffers.empty())
            throw std::runtime_error("No camera buffer allocated");
        request_ = camera_->createRequest();
        if (!request_)
            throw std::runtime_error("Unable to create camera request");
        check(request_->addBuffer(stream_, buffers[0].get()), "Request.addBuffer");
        camera_->requestCompleted.connect(this, &CameraEngine::completed);
        check(camera_->start(), "Camera.start");
        running_ = true;
    }

    ~CameraEngine() {
        if (running_)
            camera_->stop();
        request_.reset();
        allocator_.reset();
        config_.reset();
        if (camera_) {
            camera_->release();
            camera_.reset();
        }
        manager_.stop();
    }

    unsigned int width() const { return width_; }
    unsigned int height() const { return height_; }

    std::vector<unsigned char> capture() {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            finished_ = false;
            error_.clear();
        }
        check(camera_->queueRequest(request_.get()), "Camera.queueRequest");
        std::unique_lock<std::mutex> lock(mutex_);
        if (!ready_.wait_for(lock, std::chrono::seconds(8), [this] { return finished_; }))
            throw std::runtime_error("Frame completion timeout (restart worker)");
        if (!error_.empty())
            throw std::runtime_error(error_);
        auto frame = raw_;
        lock.unlock();
        request_->reuse(Request::ReuseBuffers);
        return frame;
    }

private:
    void completed(Request *req) {
        std::vector<unsigned char> captured;
        std::string error;
        if (req->status() != Request::RequestComplete) {
            error = "Cancelled camera request";
        } else {
            auto it = req->buffers().find(stream_);
            if (it == req->buffers().end() || it->second->planes().size() != 1) {
                error = "Unexpected camera buffer planes";
            } else {
                const auto &plane = it->second->planes()[0];
                const size_t map_size = static_cast<size_t>(plane.offset) + plane.length;
                void *mapping = mmap(nullptr, map_size, PROT_READ, MAP_SHARED,
                                     plane.fd.get(), 0);
                if (mapping == MAP_FAILED) {
                    error = std::string("mmap: ") + std::strerror(errno);
                } else {
                    if (plane.length < static_cast<size_t>(stride_) * (height_ - 1) + width_ * 3) {
                        error = "Camera plane smaller than RGB image";
                    } else {
                        captured.resize(static_cast<size_t>(width_) * height_ * 3);
                        auto *src = static_cast<const unsigned char *>(mapping) + plane.offset;
                        for (unsigned int row = 0; row < height_; ++row)
                            std::memcpy(captured.data() + static_cast<size_t>(row) * width_ * 3,
                                        src + static_cast<size_t>(row) * stride_, width_ * 3);
                    }
                    munmap(mapping, map_size);
                }
            }
        }
        {
            std::lock_guard<std::mutex> lock(mutex_);
            error_ = std::move(error);
            raw_ = std::move(captured);
            finished_ = true;
        }
        ready_.notify_one();
    }

    CameraManager manager_;
    std::shared_ptr<Camera> camera_;
    std::unique_ptr<CameraConfiguration> config_;
    std::unique_ptr<FrameBufferAllocator> allocator_;
    std::unique_ptr<Request> request_;
    Stream *stream_ = nullptr;
    unsigned int width_ = 0, height_ = 0, stride_ = 0;
    bool running_ = false;
    std::mutex mutex_;
    std::condition_variable ready_;
    bool finished_ = false;
    std::string error_;
    std::vector<unsigned char> raw_;
};

int main(int argc, char **argv) {
    try {
        const int interval_ms = argc > 1 ? std::stoi(argv[1]) : 2000;
        if (interval_ms < 500 || interval_ms > 60000)
            throw std::runtime_error("Capture interval must be 500-60000ms");
        CameraEngine camera;
        std::cout << "READY " << camera.width() << ' ' << camera.height() << std::endl;
        auto next_background = Clock::now();
        while (true) {
            const auto remaining = std::chrono::duration_cast<std::chrono::milliseconds>(
                next_background - Clock::now()).count();
            pollfd fd = {STDIN_FILENO, POLLIN, 0};
            const int polled = poll(&fd, 1, static_cast<int>(std::max<int64_t>(0, remaining)));
            if (polled < 0) {
                if (errno == EINTR) continue;
                throw std::runtime_error("stdin poll failed");
            }
            if (polled > 0) {
                if (fd.revents & (POLLHUP | POLLERR | POLLNVAL)) break;
                std::string command;
                if (!std::getline(std::cin, command)) break;
                if (command == "QUIT") break;
                if (command.rfind("CAPTURE ", 0) != 0) {
                    std::cout << "ERR unknown-command" << std::endl;
                    continue;
                }
                const std::string path = command.substr(8);
                if (path.empty() || path[0] != '/' || path.find('\n') != std::string::npos) {
                    std::cout << "ERR invalid-path" << std::endl;
                    continue;
                }
                const auto started = Clock::now();
                auto frame = camera.capture();
                std::ofstream output(path, std::ios::binary | std::ios::trunc);
                if (!output || !output.write(reinterpret_cast<const char *>(frame.data()),
                                              frame.size()))
                    throw std::runtime_error("Unable to write requested frame");
                const double elapsed = std::chrono::duration<double>(Clock::now() - started).count();
                std::cout << "OK " << elapsed << std::endl;
                next_background = Clock::now() + std::chrono::milliseconds(interval_ms);
            } else {
                // Low-rate image acquisition keeps the sensor warm. No frames
                // are written to disk unless explicitly requested.
                const auto started = Clock::now();
                camera.capture();
                const double duration = std::chrono::duration<double>(Clock::now() - started).count();
                if (duration > interval_ms / 1000.0)
                    std::cerr << "[CAMERA WORKER] background_capture=" << duration << "s\n";
                next_background = Clock::now() + std::chrono::milliseconds(interval_ms);
            }
        }
    } catch (const std::exception &error) {
        std::cerr << "[CAMERA WORKER] fatal: " << error.what() << std::endl;
        return 1;
    }
    return 0;
}
