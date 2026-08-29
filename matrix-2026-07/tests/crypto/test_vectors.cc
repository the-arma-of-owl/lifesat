//
// LIFESAT crypto primitive verification
//
// The in-tree SHA-256 and HMAC-SHA256 implementations are checked against published
// vectors: FIPS 180-4 and RFC 4231. Claiming correctness is not enough when the
// implementation is our own; if it does not match an independent reference, nothing
// D1 measures means anything.
//
// Build and run:  tests/gate.sh 4
//
#include "Hmac.h"
#include <cstdio>
using namespace lifesat;
int main() {
    // RFC 4231 test vectors
    struct { const char *k, *m, *want; } v[] = {
      {"\x0b\x0b\x0b\x0b\x0b\x0b\x0b\x0b\x0b\x0b\x0b\x0b\x0b\x0b\x0b\x0b\x0b\x0b\x0b\x0b",
       "Hi There",
       "b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7"},
      {"Jefe", "what do ya want for nothing?",
       "5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843"},
    };
    int fail = 0;
    for (auto &t : v) {
        std::string k(t.k, t.k[0] == 'J' ? 4 : 20);
        std::string got = hmacSha256Hex(k, t.m);
        bool ok = got == t.want;
        printf("%s  %s\n", ok ? "OK  " : "FAIL", got.c_str());
        if (!ok) { printf("      expected %s\n", t.want); fail = 1; }
    }
    printf("\nSHA-256(\"abc\") = %s\n", Sha256::hex("abc").c_str());
    printf("expected         = ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad\n");
    if (Sha256::hex("abc") != "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad") fail = 1;
    return fail;
}
