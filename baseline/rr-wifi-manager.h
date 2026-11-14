// SPDX-License-Identifier: GPL-2.0-only
// ns-3.44 interface checked against official rate-control implementations.
#ifndef RR_WIFI_MANAGER_H
#define RR_WIFI_MANAGER_H
#include "rr-core.h"
#include "ns3/wifi-module.h"
#include <vector>

namespace ns3 {
class RrWifiManager : public WifiRemoteStationManager {
  public:
    static TypeId GetTypeId() {
        static TypeId tid = TypeId("ns3::RrWifiManager")
          .SetParent<WifiRemoteStationManager>().SetGroupName("Wifi")
          .AddConstructor<RrWifiManager>()
          .AddAttribute("Algorithm", "ARF, AARF or AMRR", StringValue("AARF"),
             MakeStringAccessor(&RrWifiManager::m_algorithm), MakeStringChecker())
          .AddAttribute("PaperRates", "Use 6/12/18/36/54 Mb/s", BooleanValue(true),
             MakeBooleanAccessor(&RrWifiManager::m_paperRates), MakeBooleanChecker())
          .AddAttribute("MinSuccess", "ARF/AARF minimum success count", UintegerValue(10),
             MakeUintegerAccessor(&RrWifiManager::m_minSuccess), MakeUintegerChecker<uint32_t>(1))
          .AddAttribute("MaxSuccess", "AARF maximum success count", UintegerValue(50),
             MakeUintegerAccessor(&RrWifiManager::m_maxSuccess), MakeUintegerChecker<uint32_t>(1))
          .AddAttribute("MinTimeout", "Minimum packet timer", UintegerValue(15),
             MakeUintegerAccessor(&RrWifiManager::m_minTimeout), MakeUintegerChecker<uint32_t>(1))
          .AddAttribute("SuccessK", "AARF success multiplier", DoubleValue(2),
             MakeDoubleAccessor(&RrWifiManager::m_successK), MakeDoubleChecker<double>(1))
          .AddAttribute("TimeoutK", "AARF timeout multiplier", DoubleValue(1.5),
             MakeDoubleAccessor(&RrWifiManager::m_timeoutK), MakeDoubleChecker<double>(1))
          .AddAttribute("AmrrMaxSuccess", "Maximum successful AMRR periods", UintegerValue(15),
             MakeUintegerAccessor(&RrWifiManager::m_amrrMax), MakeUintegerChecker<uint32_t>(1))
          .AddAttribute("UpdatePeriod", "AMRR update period", TimeValue(Seconds(1)),
             MakeTimeAccessor(&RrWifiManager::m_period), MakeTimeChecker(MilliSeconds(1)))
          .AddTraceSource("Rate", "Selected DATA rate, bits/s",
             MakeTraceSourceAccessor(&RrWifiManager::m_currentRate), "ns3::TracedValueCallback::Uint64")
          .AddTraceSource("State", "rate index, threshold, timer, retry, recovery after feedback",
             MakeTraceSourceAccessor(&RrWifiManager::m_state), "ns3::RrWifiManager::StateCallback");
        return tid;
    }
  private:
    struct Station : WifiRemoteStation {
        rr::Arf arf;
        rr::Amrr amrr;
        Time nextUpdate;
    };
    std::string m_algorithm;
    bool m_paperRates;
    uint32_t m_minSuccess, m_maxSuccess, m_minTimeout, m_amrrMax;
    double m_successK, m_timeoutK;
    Time m_period;
    TracedValue<uint64_t> m_currentRate{0};
    TracedCallback<uint32_t,uint32_t,uint32_t,uint32_t,bool> m_state;
    void DoInitialize() override {
        NS_ABORT_MSG_IF(m_algorithm!="ARF" && m_algorithm!="AARF" && m_algorithm!="AMRR", "Unknown Algorithm");
        NS_ABORT_MSG_IF(GetHtSupported() || GetVhtSupported() || GetHeSupported(), "Use legacy 802.11a only");
        WifiRemoteStationManager::DoInitialize();
    }
    WifiRemoteStation* DoCreateStation() const override {
        auto s = new Station;
        rr::Parameters p;
        p.minSuccess=m_minSuccess; p.maxSuccess=m_maxSuccess; p.minTimeout=m_minTimeout;
        p.successK=m_successK; p.timeoutK=m_timeoutK;
        s->arf=rr::Arf(m_algorithm=="AARF",p);
        s->amrr.maxThreshold=m_amrrMax;
        s->nextUpdate=Simulator::Now()+m_period;
        return s;
    }
    std::vector<WifiMode> Modes(WifiRemoteStation* s) const {
        std::vector<WifiMode> modes;
        for(uint8_t i=0;i<GetNSupported(s);++i) {
            auto mode=GetSupported(s,i);
            auto bps=mode.GetDataRate(MHz_u{20});
            if (!m_paperRates || bps==6000000 || bps==12000000 || bps==18000000 ||
                bps==36000000 || bps==54000000) modes.push_back(mode);
        }
        std::sort(modes.begin(), modes.end(), [](WifiMode a,WifiMode b) {
            return a.GetDataRate(MHz_u{20}) < b.GetDataRate(MHz_u{20});
        });
        NS_ABORT_MSG_IF(modes.empty(), "No supported OFDM rates");
        return modes;
    }
    void Emit(Station* s) {
        if(m_algorithm=="AMRR") m_state(s->amrr.rate,s->amrr.threshold,0,s->amrr.retry,s->amrr.recovery);
        else m_state(s->arf.rate,s->arf.threshold,s->arf.timer,s->arf.retry,s->arf.recovery);
    }
    void DoReportRxOk(WifiRemoteStation*,double,WifiMode) override {}
    void DoReportRtsFailed(WifiRemoteStation*) override {}
    void DoReportRtsOk(WifiRemoteStation*,double,WifiMode,double) override {}
    void DoReportFinalRtsFailed(WifiRemoteStation* st) override {
        auto s=static_cast<Station*>(st);
        s->arf.FinalFailure(); s->amrr.FinalFailure();
    }
    void DoReportFinalDataFailed(WifiRemoteStation* st) override {
        auto s=static_cast<Station*>(st);
        s->arf.FinalFailure(); s->amrr.FinalFailure(); Emit(s);
    }
    void DoReportDataFailed(WifiRemoteStation* st) override {
        auto s=static_cast<Station*>(st);
        if(m_algorithm=="AMRR") s->amrr.Fail(); else s->arf.Fail();
        Emit(s);
    }
    void DoReportDataOk(WifiRemoteStation* st,double,WifiMode,double,MHz_u,uint8_t) override {
        auto s=static_cast<Station*>(st);
        if(m_algorithm=="AMRR") s->amrr.Ok(); else s->arf.Ok(Modes(s).size());
        Emit(s);
    }
    WifiTxVector VectorFor(WifiMode mode) {
        return WifiTxVector(mode,GetDefaultTxPowerLevel(),
           GetPreambleForTransmission(mode.GetModulationClass(),GetShortPreambleEnabled()),
           NanoSeconds(800),1,1,0,MHz_u{20},false);
    }
    WifiTxVector DoGetDataTxVector(WifiRemoteStation* st,MHz_u) override {
        auto s=static_cast<Station*>(st);
        auto modes=Modes(s);
        uint32_t index;
        if(m_algorithm=="AMRR") {
            if(Simulator::Now()>=s->nextUpdate) {
                s->amrr.Update(modes.size());
                s->nextUpdate=Simulator::Now()+m_period;
                Emit(s);
            }
            index=s->amrr.TxRate();
        } else index=s->arf.rate;
        NS_ABORT_MSG_IF(index>=modes.size(), "Rate index out of bounds");
        m_currentRate=modes[index].GetDataRate(MHz_u{20});
        return VectorFor(modes[index]);
    }
    WifiTxVector DoGetRtsTxVector(WifiRemoteStation* st) override {
        return VectorFor(Modes(st).front());
    }
};
NS_OBJECT_ENSURE_REGISTERED(RrWifiManager);
} // namespace ns3
#endif
