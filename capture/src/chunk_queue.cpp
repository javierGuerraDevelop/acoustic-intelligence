#include "radar/chunk_queue.hpp"

#include <algorithm>

namespace radar {

ChunkQueue::ChunkQueue(std::size_t max_chunks)
    : max_chunks_(std::max<std::size_t>(max_chunks, 1))
{
}

void ChunkQueue::push(std::shared_ptr<const AudioChunk> chunk)
{
    if (chunk == nullptr) {
        return;
    }
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (closed_) {
            return;
        }
        while (queue_.size() >= max_chunks_) {
            queue_.pop_front();
            ++dropped_;
        }
        queue_.push_back(std::move(chunk));
    }
    ready_.notify_one();
}

std::shared_ptr<const AudioChunk> ChunkQueue::pop(std::chrono::milliseconds timeout)
{
    std::unique_lock<std::mutex> lock(mutex_);
    if (!ready_.wait_for(lock, timeout, [this] { return closed_ || !queue_.empty(); })) {
        return nullptr;
    }
    if (queue_.empty()) {
        return nullptr;
    }
    auto chunk = std::move(queue_.front());
    queue_.pop_front();
    return chunk;
}

void ChunkQueue::close()
{
    {
        std::lock_guard<std::mutex> lock(mutex_);
        closed_ = true;
    }
    ready_.notify_all();
}

void ChunkQueue::clear()
{
    std::lock_guard<std::mutex> lock(mutex_);
    queue_.clear();
}

std::size_t ChunkQueue::size() const
{
    std::lock_guard<std::mutex> lock(mutex_);
    return queue_.size();
}

std::size_t ChunkQueue::dropped() const
{
    std::lock_guard<std::mutex> lock(mutex_);
    return dropped_;
}

} // namespace radar
