//
// LIFESAT HMAC-SHA256 for command authentication
//
// The plan called for ed25519 signatures; HMAC-SHA256 is used instead because CCSDS
// SDLS telecommand authentication is symmetric (CMAC/HMAC family), not public-key.
// Section 3.4 already states that D1 models command authorisation abstractly rather
// than implementing SDLS; the abstracted property is message authentication plus
// freshness.
//
// No shortcut: the tag is computed and compared, so a tampered command fails
// arithmetically rather than by assumption.
//
#ifndef __LIFESAT_HMAC_H
#define __LIFESAT_HMAC_H

#include <string>
#include "HashChain.h"

namespace lifesat {

/**
 * FIPS 198-1 HMAC-SHA256.
 *
 *   HMAC(K, m) = H( (K' ^ opad) || H( (K' ^ ipad) || m ) )
 */
inline std::string hmacSha256Hex(const std::string& key, const std::string& message)
{
    const size_t BLOCK = 64;
    std::string k = key;

    if (k.size() > BLOCK) {                    // a long key is hashed first
        std::string digest = Sha256::hex(k);
        std::string raw;
        for (size_t i = 0; i < digest.size(); i += 2)
            raw += (char)std::stoi(digest.substr(i, 2), nullptr, 16);
        k = raw;
    }
    k.resize(BLOCK, '\0');

    std::string inner(BLOCK, '\0'), outer(BLOCK, '\0');
    for (size_t i = 0; i < BLOCK; i++) {
        inner[i] = (char)(k[i] ^ 0x36);
        outer[i] = (char)(k[i] ^ 0x5c);
    }

    Sha256 h1;
    h1.update(inner);
    h1.update(message);
    std::string innerHex = h1.hexDigest();
    std::string innerRaw;
    for (size_t i = 0; i < innerHex.size(); i += 2)
        innerRaw += (char)std::stoi(innerHex.substr(i, 2), nullptr, 16);

    Sha256 h2;
    h2.update(outer);
    h2.update(innerRaw);
    return h2.hexDigest();
}

/** Constant-time comparison -- side-channel habit, and it costs nothing. */
inline bool constantTimeEquals(const std::string& a, const std::string& b)
{
    if (a.size() != b.size())
        return false;
    unsigned char diff = 0;
    for (size_t i = 0; i < a.size(); i++)
        diff |= (unsigned char)(a[i] ^ b[i]);
    return diff == 0;
}

} // namespace lifesat

#endif
