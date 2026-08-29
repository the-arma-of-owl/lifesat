#!/usr/bin/env bash
set -u
cd "$(dirname "$0")"
"${CXX:-c++}" -std=c++17 -O2 -I../../src -o /tmp/lifesat_crypto_test test_vectors.cc || exit 1
/tmp/lifesat_crypto_test
