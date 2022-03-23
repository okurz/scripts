#!/usr/bin/env bash

set -e
dir=$(cd "$(dirname "${BASH_SOURCE[0]}")"; pwd)

TEST_MORE_PATH=$dir/../test-more-bash
BASHLIB="`
    find $TEST_MORE_PATH -type d |
    grep -E '/(bin|lib)$' |
    xargs -n1 printf "%s:"`"
PATH=$BASHLIB$PATH

source bash+ :std
use Test::More
plan tests 4

call_retry() {
    $dir/../retry $*
}

rc=0
output=$(call_retry true 2>&1) || rc=$?
is "$rc" 0 'successful retry'
like "$output" '' 'no output for no retries'

rc=0
output=$(call_retry false 2>&1) || rc=$?
is "$rc" 1 'retry fails with non-zero exit code on exhausted retries'
like "$output" 'Retrying up to 0.*times' 'output for exhausted retries'

fails=2
cmd_fails_twice_then_succeeds() {
    return 0
}

tmp=$(mktemp)
trap 'rm "$tmp"' EXIT
echo 3 > $tmp
export tmp
rc=0
output=$(retry bash -c 'x=$(cat $tmp); ((x--)); echo $x > $tmp; [[ $x = 0 ]]' 2>&1) || rc=$?
is "$rc" 0 'retry eventually succeeds'
like "$output" 'Retrying up to 2.*times' 'output for at least two retries…'
unlike "$output" 'Retrying up to 1.*times' '… but not more'
