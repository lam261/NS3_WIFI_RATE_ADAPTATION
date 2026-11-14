// SPDX-License-Identifier: GPL-2.0-only
// Target API: ns-3.44. Copy this file AND both rr-*.h to scratch/.
#include "ns3/core-module.h"
#include "ns3/network-module.h"
#include "ns3/internet-module.h"
#include "ns3/mobility-module.h"
#include "ns3/wifi-module.h"
#include "ns3/flow-monitor-module.h"
#include "ns3/applications-module.h"
#include "rr-wifi-manager.h"
#include <fstream>
#include <iomanip>
#include <sstream>
#include <cmath>

using namespace ns3;
namespace {
// UDP payload includes a 12-byte sequence/timestamp header.
constexpr uint32_t HEADER=12;
// 2268 UDP + 28 IPv4/UDP + 8 LLC = 2304-byte MSDU. No IP fragmentation.
uint32_t g_size=2268, g_count=30000;
double g_interval=0.0008, g_start=2, g_duration=24;
uint64_t g_sent=0, g_received=0, g_bytes=0, g_fail=0, g_final=0;
double g_delay=0;
Ptr<Socket> g_sender;
std::ofstream g_series,g_rate,g_state;
double g_bin=1;
uint64_t g_binBytes=0;

void Send(uint32_t sequence) {
    if(sequence>=g_count) return;
    SeqTsHeader header; header.SetSeq(sequence);
    auto packet=Create<Packet>(g_size-HEADER); packet->AddHeader(header);
    int result=g_sender->Send(packet);
    if(result==static_cast<int>(g_size)) ++g_sent;
    if(sequence+1<g_count) Simulator::Schedule(Seconds(g_interval),&Send,sequence+1);
}
void Receive(Ptr<Socket> socket) {
    while(auto packet=socket->Recv()) {
        if(Simulator::Now()<Seconds(g_start) || Simulator::Now()>=Seconds(g_start+g_duration)) continue;
        SeqTsHeader header;
        if(packet->GetSize()<HEADER) continue;
        uint32_t bytes=packet->GetSize(); packet->RemoveHeader(header);
        ++g_received; g_bytes+=bytes; g_binBytes+=bytes;
        g_delay+=(Simulator::Now()-header.GetTs()).GetSeconds();
    }
}
void Sample(double previous) {
    double now=Simulator::Now().GetSeconds();
    g_series << std::setprecision(12) << now << ',' << g_binBytes*8.0/(now-previous)/1e6 << '\n';
    g_binBytes=0;
    double next=std::min(now+g_bin,g_start+g_duration);
    if(next>now+1e-9) Simulator::Schedule(Seconds(next-now),&Sample,now);
}
void Rate(uint64_t,uint64_t next) {g_rate << Simulator::Now().GetSeconds() << ',' << next/1e6 << '\n';}
void State(uint32_t r,uint32_t th,uint32_t timer,uint32_t retry,bool recovery) {
    g_state << Simulator::Now().GetSeconds() << ',' << r << ',' << th << ',' << timer << ',' << retry << ',' << recovery << '\n';
}
bool Measuring() {
    const double now=Simulator::Now().GetSeconds();
    return now>=g_start && now<g_start+g_duration;
}
void Failure(Mac48Address) {if(Measuring()) ++g_fail;}
void FinalFailure(Mac48Address) {if(Measuring()) ++g_final;}
}

int main(int argc,char* argv[]) {
    std::string algorithm="AARF",scenario="static",prefix="rr",fixedMode="OfdmRate18Mbps";
    double distance=60,nearDistance=10,farDistance=100,txPower=16,noiseFigure=7;
    double exponent=3,referenceLoss=46.6777,switchTime=12,drain=1,amrrPeriod=1;
    uint32_t seed=1,run=1,minSuccess=10,maxSuccess=50,minTimeout=15;
    double successK=2,timeoutK=1.5;
    bool rts=false,paperRates=true,pcap=false,traceState=false;
    CommandLine cmd(__FILE__);
    cmd.AddValue("algorithm","ARF/AARF/AMRR/Fixed",algorithm);
    cmd.AddValue("scenario","static/step",scenario);
    cmd.AddValue("prefix","Output prefix (parent directory must exist)",prefix);
    cmd.AddValue("distance","Static distance in m",distance);
    cmd.AddValue("nearDistance","Step first distance, m",nearDistance);
    cmd.AddValue("farDistance","Step second distance, m",farDistance);
    cmd.AddValue("switchTime","Step time relative to traffic start, s",switchTime);
    cmd.AddValue("duration","Measurement window in s",g_duration);
    cmd.AddValue("interval","CBR inter-packet time, s",g_interval);
    cmd.AddValue("packets","Maximum number of UDP packets",g_count);
    cmd.AddValue("packetSize","UDP payload including 12-byte SeqTsHeader",g_size);
    cmd.AddValue("drain","Extra simulation time after measurement",drain);
    cmd.AddValue("sample","Goodput sample width, s",g_bin);
    cmd.AddValue("rts","Use RTS/CTS",rts);
    cmd.AddValue("paperRates","Adaptive rates: 6,12,18,36,54 only",paperRates);
    cmd.AddValue("fixedMode","Data mode for Fixed",fixedMode);
    cmd.AddValue("txPower","Transmit power dBm",txPower);
    cmd.AddValue("noiseFigure","Receiver noise figure dB",noiseFigure);
    cmd.AddValue("exponent","Log-distance exponent",exponent);
    cmd.AddValue("referenceLoss","Loss at 1 m, dB",referenceLoss);
    cmd.AddValue("minSuccess","ARF/AARF success threshold minimum",minSuccess);
    cmd.AddValue("maxSuccess","AARF success threshold maximum",maxSuccess);
    cmd.AddValue("minTimeout","ARF/AARF minimum packet timer",minTimeout);
    cmd.AddValue("successK","AARF success multiplier",successK);
    cmd.AddValue("timeoutK","AARF timeout multiplier",timeoutK);
    cmd.AddValue("amrrPeriod","AMRR decision interval, s",amrrPeriod);
    cmd.AddValue("seed","RNG seed",seed); cmd.AddValue("run","Independent RNG run",run);
    cmd.AddValue("pcap","Write radiotap PCAP",pcap);
    cmd.AddValue("traceState","Write per-feedback state CSV (large)",traceState);
    cmd.Parse(argc,argv);
    NS_ABORT_MSG_IF(algorithm!="ARF" && algorithm!="AARF" && algorithm!="AMRR" && algorithm!="Fixed","Bad algorithm");
    NS_ABORT_MSG_IF(scenario!="static" && scenario!="step","Bad scenario");
    NS_ABORT_MSG_IF(!std::isfinite(g_duration) || g_duration<=0 || !std::isfinite(g_interval) ||
       g_interval<=0 || g_size<HEADER || g_size>2268 || !g_count || !std::isfinite(g_bin) ||
       g_bin<=0 || drain<0 || distance<=0 || nearDistance<=0 || farDistance<=0 || amrrPeriod<=0,
       "Invalid timing, size or distance");
    NS_ABORT_MSG_IF((g_count-1)*g_interval>=g_duration,"Last send must precede measurement end; increase duration or lower packets");
    NS_ABORT_MSG_IF(scenario=="step" && (switchTime<=0 || switchTime>=g_duration),"switchTime outside measurement");
    RngSeedManager::SetSeed(seed); RngSeedManager::SetRun(run);
    // Avoid queue-lifetime expiry silently removing an in-progress retry chain.
    // Tail drop remains possible and is reflected in application PDR.
    Config::SetDefault("ns3::WifiMacQueue::MaxSize",QueueSizeValue(QueueSize("500p")));
    Config::SetDefault("ns3::WifiMacQueue::MaxDelay",TimeValue(Seconds(g_start+g_duration+drain+1)));
    g_series.open(prefix+"-timeseries.csv"); g_rate.open(prefix+"-rates.csv");
    g_state.open(prefix+"-state.csv");
    NS_ABORT_MSG_IF(!g_series || !g_rate || !g_state,"Cannot open output prefix");
    g_series << "time_s,goodput_mbps\n"; g_rate << "time_s,selected_data_rate_mbps\n";
    g_state << "time_s,rate_index,success_threshold,timer,retry,recovery\n";

    NodeContainer nodes; nodes.Create(2); // 0=A receiver, 1=B sender
    MobilityHelper mobility; mobility.SetMobilityModel("ns3::ConstantPositionMobilityModel"); mobility.Install(nodes);
    nodes.Get(0)->GetObject<MobilityModel>()->SetPosition(Vector(0,0,0));
    auto moving=nodes.Get(1)->GetObject<MobilityModel>();
    moving->SetPosition(Vector(scenario=="static"?distance:nearDistance,0,0));
    if(scenario=="step") Simulator::Schedule(Seconds(g_start+switchTime),[moving,farDistance]() {
        moving->SetPosition(Vector(farDistance,0,0));
    });

    YansWifiChannelHelper channel;
    channel.SetPropagationDelay("ns3::ConstantSpeedPropagationDelayModel");
    channel.AddPropagationLoss("ns3::LogDistancePropagationLossModel","Exponent",DoubleValue(exponent),
       "ReferenceDistance",DoubleValue(1),"ReferenceLoss",DoubleValue(referenceLoss));
    YansWifiPhyHelper phy; phy.SetChannel(channel.Create());
    phy.Set("ChannelSettings",StringValue("{36, 20, BAND_5GHZ, 0}"));
    phy.Set("TxPowerStart",DoubleValue(txPower)); phy.Set("TxPowerEnd",DoubleValue(txPower));
    phy.Set("RxNoiseFigure",DoubleValue(noiseFigure));
    phy.SetErrorRateModel("ns3::NistErrorRateModel");
    phy.SetPcapDataLinkType(WifiPhyHelper::DLT_IEEE802_11_RADIO);
    WifiHelper wifi; wifi.SetStandard(WIFI_STANDARD_80211a);
    const uint32_t rtsThreshold=rts?0:65535;
    if(algorithm=="Fixed") wifi.SetRemoteStationManager("ns3::ConstantRateWifiManager",
       "DataMode",StringValue(fixedMode),"ControlMode",StringValue("OfdmRate6Mbps"),
       "RtsCtsThreshold",UintegerValue(rtsThreshold),"FragmentationThreshold",UintegerValue(65535),
       "NonUnicastMode",StringValue("OfdmRate6Mbps"));
    else wifi.SetRemoteStationManager("ns3::RrWifiManager","Algorithm",StringValue(algorithm),
       "PaperRates",BooleanValue(paperRates),"MinSuccess",UintegerValue(minSuccess),
       "MaxSuccess",UintegerValue(maxSuccess),"MinTimeout",UintegerValue(minTimeout),
       "SuccessK",DoubleValue(successK),"TimeoutK",DoubleValue(timeoutK),
       "UpdatePeriod",TimeValue(Seconds(amrrPeriod)),"RtsCtsThreshold",UintegerValue(rtsThreshold),
       "FragmentationThreshold",UintegerValue(65535),"NonUnicastMode",StringValue("OfdmRate6Mbps"));
    WifiMacHelper mac; mac.SetType("ns3::AdhocWifiMac","QosSupported",BooleanValue(false),
       "FrameRetryLimit",UintegerValue(4));
    auto devices=wifi.Install(phy,mac,nodes); wifi.AssignStreams(devices,10);
    InternetStackHelper internet; internet.Install(nodes);
    Ipv4AddressHelper ip; ip.SetBase("10.1.1.0","255.255.255.0"); auto addresses=ip.Assign(devices);
    auto manager=DynamicCast<WifiNetDevice>(devices.Get(1))->GetRemoteStationManager();
    if(algorithm!="Fixed") {
        NS_ABORT_MSG_IF(!manager->TraceConnectWithoutContext("Rate",MakeCallback(&Rate)),"Rate trace missing");
        if(traceState) NS_ABORT_MSG_IF(!manager->TraceConnectWithoutContext("State",MakeCallback(&State)),"State trace missing");
    }
    NS_ABORT_MSG_IF(!manager->TraceConnectWithoutContext("MacTxDataFailed",MakeCallback(&Failure)),"Failure trace missing");
    NS_ABORT_MSG_IF(!manager->TraceConnectWithoutContext("MacTxFinalDataFailed",MakeCallback(&FinalFailure)),"Final-failure trace missing");
    if(pcap) phy.EnablePcap(prefix,devices);
    auto receiver=Socket::CreateSocket(nodes.Get(0),UdpSocketFactory::GetTypeId());
    NS_ABORT_MSG_IF(receiver->Bind(InetSocketAddress(Ipv4Address::GetAny(),9000))<0,"UDP bind failed");
    receiver->SetRecvCallback(MakeCallback(&Receive));
    g_sender=Socket::CreateSocket(nodes.Get(1),UdpSocketFactory::GetTypeId());
    g_sender->Bind(); g_sender->Connect(InetSocketAddress(addresses.GetAddress(0),9000));
    FlowMonitorHelper flowHelper; auto monitor=flowHelper.InstallAll();
    Simulator::Schedule(Seconds(g_start),&Send,0);
    Simulator::Schedule(Seconds(g_start+std::min(g_bin,g_duration)),&Sample,g_start);
    Simulator::Stop(Seconds(g_start+g_duration+drain)); Simulator::Run();
    monitor->CheckForLostPackets(); monitor->SerializeToXmlFile(prefix+"-flow.xml",true,true);
    std::ofstream summary(prefix+"-summary.csv"); NS_ABORT_MSG_IF(!summary,"Cannot write summary");
    summary << "algorithm,scenario,distance_m,near_m,far_m,switch_s,rts,paper_rates,seed,run,duration_s,packet_size,planned_packets,interval_s,offered_mbps,tx_packets,rx_packets,goodput_mbps,pdr,mean_delay_ms,data_failed_callbacks,final_data_failed_callbacks,tx_power_dbm,noise_figure_db,exponent,reference_loss_db,min_success,max_success,min_timeout,success_k,timeout_k,amrr_period_s,fixed_mode\n";
    summary << std::setprecision(12) << algorithm << ',' << scenario << ',' << distance << ',' << nearDistance << ',' << farDistance << ',' << switchTime << ',' << rts << ',' << paperRates << ',' << seed << ',' << run << ',' << g_duration << ',' << g_size << ',' << g_count << ',' << g_interval << ',' << g_size*8/g_interval/1e6 << ',' << g_sent << ',' << g_received << ',' << g_bytes*8.0/g_duration/1e6 << ',' << (g_sent?double(g_received)/g_sent:0) << ',';
    if(g_received) summary << g_delay/g_received*1000; else summary << "nan";
    summary << ',' << g_fail << ',' << g_final << ',' << txPower << ',' << noiseFigure << ',' << exponent << ',' << referenceLoss << ',' << minSuccess << ',' << maxSuccess << ',' << minTimeout << ',' << successK << ',' << timeoutK << ',' << amrrPeriod << ',' << fixedMode << '\n';
    std::cout << "goodput=" << g_bytes*8.0/g_duration/1e6 << " Mb/s; received=" << g_received << '/' << g_sent << "; prefix=" << prefix << '\n';
    receiver->Close(); g_sender->Close(); g_sender=nullptr;
    Simulator::Destroy(); return 0;
}
