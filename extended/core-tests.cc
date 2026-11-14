// Compile independently of ns-3: g++ -std=c++17 core-tests.cc -o core-tests
#include "rr-ext-core.h"
#include <cassert>
#include <iostream>
int main() {
    rr::Arf a;
    for (int i=0;i<10;++i) a.Ok(5);
    assert(a.rate==1 && a.recovery && a.timer==0);
    a.Fail();
    assert(a.rate==0 && a.threshold==20 && a.timeout==30 && a.recovery);
    a.Ok(5);
    assert(!a.recovery && a.success==1);
    for (int i=1;i<20;++i) a.Ok(5);
    assert(a.rate==1 && a.recovery);
    a.Fail();
    assert(a.threshold==40 && a.timeout==60 && a.rate==0);
    a.FinalFailure();
    a.rate=1; a.recovery=true; a.Fail();
    assert(a.threshold==50 && a.timeout==75);
    a.rate=2; a.recovery=false; a.retry=0;
    a.Fail(); assert(a.rate==2);
    a.Fail(); assert(a.rate==1 && a.threshold==10 && a.timeout==15);
    rr::Arf baseline(false);
    for(int i=0;i<10;++i) baseline.Ok(5);
    baseline.Fail(); assert(baseline.threshold==10 && baseline.timeout==15);
    rr::Parameters p; p.minSuccess=100; p.maxSuccess=100;
    rr::Arf t(true,p);
    for(int i=0;i<15;++i) t.Ok(5);
    assert(t.rate==0 && t.timer==15);
    t.Ok(5); assert(t.rate==1); // pre-increment comparison in RR
    rr::Amrr m;
    for(int i=0;i<9;++i) m.Ok();
    m.Update(5); assert(m.rate==0 && m.packets==9);
    m.Ok(); m.Update(5); assert(m.rate==1 && m.recovery);
    m.Fail(); m.FinalFailure(); m.Update(5);
    assert(m.rate==0 && m.threshold==2 && !m.recovery);
    m.rate=4; m.retry=0; assert(m.TxRate()==4);
    m.retry=1; assert(m.TxRate()==3);
    m.retry=2; assert(m.TxRate()==2);
    m.retry=3; assert(m.TxRate()==0);
    rr::Amrr n;
    n.Fail(); n.Fail(); n.Ok();
    assert(n.packets==1 && n.attempts==3 && n.failedAttempts==2);
    rr::Arf limits;
    for(int i=0;i<10000;++i) {limits.Ok(5); assert(limits.rate<5);}
    for(int i=0;i<100;++i) {limits.Fail(); assert(limits.rate<5);}
    std::cout << "PASS: AARF probe/backoff/cap, normal fallback, ARF, timer ordering, "
                 "AMRR sample window/recovery/retry chain, distinct packets, rate bounds\n";
}
