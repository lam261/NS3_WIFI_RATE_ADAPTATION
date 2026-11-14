// SPDX-License-Identifier: GPL-2.0-only
// Independent state machines, interpreted from INRIA RR-5208, Appendices A/B.
#ifndef RR_CORE_H
#define RR_CORE_H
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <stdexcept>

namespace rr {
struct Parameters {
    uint32_t minSuccess = 10, maxSuccess = 50, minTimeout = 15;
    double successK = 2, timeoutK = 1.5;
    void Validate() const {
        if (!minSuccess || maxSuccess < minSuccess || !minTimeout ||
            !std::isfinite(successK) || successK < 1 ||
            !std::isfinite(timeoutK) || timeoutK < 1)
            throw std::invalid_argument("Invalid ARF/AARF parameters");
    }
};
struct Arf {
    Parameters p;
    bool adaptive;
    uint32_t rate = 0, success = 0, timer = 0, retry = 0;
    uint32_t threshold, timeout;
    bool recovery = false;
    explicit Arf(bool aarf = true, Parameters params = Parameters())
        : p(params), adaptive(aarf), threshold(p.minSuccess), timeout(p.minTimeout) {
        p.Validate();
    }
    void Ok(uint32_t numberOfRates) {
        ++success;
        retry = 0;
        // RR p.23: compare timer BEFORE increment on a successful transmission.
        if ((success == threshold || timer == timeout) && rate + 1 < numberOfRates) {
            ++rate; timer = 0; success = 0; recovery = true;
        } else {
            ++timer; recovery = false;
        }
    }
    void Fail() {
        ++timer; ++retry; success = 0;
        if (recovery) {
            timer = 0;
            if (retry == 1) {
                if (adaptive) {
                    threshold = static_cast<uint32_t>(std::min(
                        threshold * p.successK, static_cast<double>(p.maxSuccess)));
                    timeout = static_cast<uint32_t>(std::max(
                        p.timeoutK * threshold, static_cast<double>(p.minTimeout)));
                }
                if (rate) --rate;
            }
        } else {
            if (retry % 2 == 0) {
                if (adaptive) {threshold = p.minSuccess; timeout = p.minTimeout;}
                if (rate) --rate;
            }
            if (retry >= 2) timer = 0;
        }
    }
    // RR send_one_packet initializes retry for each new packet, but retains recovery.
    void FinalFailure() { retry = 0; }
};

struct Amrr {
    uint32_t rate = 0, retry = 0, success = 0, threshold = 1;
    uint32_t minThreshold = 1, maxThreshold = 15;
    uint64_t attempts = 0, failedAttempts = 0, packets = 0;
    bool recovery = false;
    // Explicit interpretation: failure fraction = failed attempts / all attempts;
    // is_enough counts DISTINCT packets, as Appendix B states (>=10).
    void Ok() {
        if (retry == 0) ++packets;
        ++attempts; retry = 0;
    }
    void Fail() {
        if (retry == 0) ++packets;
        ++attempts; ++failedAttempts; ++retry;
    }
    void FinalFailure() { retry = 0; } // already counted by Fail; do not count twice
    void Update(uint32_t numberOfRates) {
        if (!attempts) return;
        const double fraction = static_cast<double>(failedAttempts) / attempts;
        const bool enough = packets >= 10;
        bool changed = false;
        if (fraction < 0.10 && enough) {
            ++success;
            if (success >= threshold && rate + 1 < numberOfRates) {
                recovery = true; success = 0; ++rate; changed = true;
            } else recovery = false;
        } else if (fraction > 0.33) {
            success = 0;
            // Interpret the inconsistent g_recovery/m_recovery in printed code
            // as one flag; inspect its PREVIOUS value before clearing it.
            if (rate) {
                threshold = recovery ? std::min(threshold * 2, maxThreshold) : minThreshold;
                --rate; changed = true;
            }
            recovery = false;
        }
        if (enough || changed) {attempts = 0; failedAttempts = 0; packets = 0;}
    }
    uint32_t TxRate() const {
        if (retry == 0) return rate;
        if (retry == 1) return rate ? rate - 1 : 0;
        if (retry == 2) return rate > 1 ? rate - 2 : 0;
        return 0; // r3 is ALWAYS minimum, not rate-3
    }
};
} // namespace rr
#endif
