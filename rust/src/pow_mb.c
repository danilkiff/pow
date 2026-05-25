/* C shim over ISA-L Crypto multi-buffer SHA-256.
 * Hides the size/alignment of ISAL_SHA256_HASH_CTX{,_MGR} and exposes a
 * simple void*-based API for the Rust side.
 */
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <isa-l_crypto/sha256_mb.h>
#include <isa-l_crypto/multi_buffer.h>

size_t pow_mb_mgr_size(void)  { return sizeof(ISAL_SHA256_HASH_CTX_MGR); }
size_t pow_mb_mgr_align(void) { return _Alignof(ISAL_SHA256_HASH_CTX_MGR); }
size_t pow_mb_ctx_size(void)  { return sizeof(ISAL_SHA256_HASH_CTX); }
size_t pow_mb_ctx_align(void) { return _Alignof(ISAL_SHA256_HASH_CTX); }

int pow_mb_mgr_init(void *mgr) {
    return isal_sha256_ctx_mgr_init((ISAL_SHA256_HASH_CTX_MGR *)mgr);
}

void pow_mb_ctx_reset(void *ctx) {
    /* IDLE = 0, so a full memset is the safe reset. */
    memset(ctx, 0, sizeof(ISAL_SHA256_HASH_CTX));
}

/* submit_entire: one attempt == one whole message (FIRST|LAST). */
int pow_mb_submit_entire(void *mgr, void *ctx, void **completed_out,
                         const void *buf, uint32_t len) {
    ISAL_SHA256_HASH_CTX *out = NULL;
    int rc = isal_sha256_ctx_mgr_submit(
        (ISAL_SHA256_HASH_CTX_MGR *)mgr,
        (ISAL_SHA256_HASH_CTX *)ctx,
        &out, buf, len, ISAL_HASH_ENTIRE);
    *completed_out = out;
    return rc;
}

int pow_mb_flush(void *mgr, void **completed_out) {
    ISAL_SHA256_HASH_CTX *out = NULL;
    int rc = isal_sha256_ctx_mgr_flush(
        (ISAL_SHA256_HASH_CTX_MGR *)mgr, &out);
    *completed_out = out;
    return rc;
}

/* result_digest is uint32_t[8] in host endianness; SHA-256's canonical
 * output is big-endian, so we swap bytes explicitly here. */
void pow_mb_ctx_digest(const void *ctx, uint8_t out[32]) {
    const ISAL_SHA256_HASH_CTX *c = (const ISAL_SHA256_HASH_CTX *)ctx;
    for (int i = 0; i < 8; i++) {
        uint32_t w = c->job.result_digest[i];
        out[i*4+0] = (uint8_t)(w >> 24);
        out[i*4+1] = (uint8_t)(w >> 16);
        out[i*4+2] = (uint8_t)(w >>  8);
        out[i*4+3] = (uint8_t)(w);
    }
}

void pow_mb_ctx_set_user(void *ctx, uint64_t v) {
    ((ISAL_SHA256_HASH_CTX *)ctx)->user_data = (void *)(uintptr_t)v;
}
uint64_t pow_mb_ctx_get_user(const void *ctx) {
    return (uint64_t)(uintptr_t)((const ISAL_SHA256_HASH_CTX *)ctx)->user_data;
}
