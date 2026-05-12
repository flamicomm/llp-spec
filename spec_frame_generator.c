/**
 * spec_frame_generator.c — LLP Spec Reference Frame Generator
 *
 * Generates hex-encoded frames for all valid LLP test vectors using the
 * reference C implementation. Output is consumed by build_vectors.py.
 *
 * Compile: gcc -std=c99 -I /path/to/llp-protocol/include -o /tmp/spec_gen spec_frame_generator.c
 * Usage:   /tmp/spec_gen
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "llp_protocol.h"

#define MAX_PAYLOAD 512

typedef struct {
    const char* name;
    const uint8_t* data;
    uint16_t len;
    const char* desc;
} raw_vector_t;

typedef struct {
    const char* name;
    const uint8_t* chain;
    uint16_t chain_len;
    const char* desc;
} layer_vector_t;

static void print_hex(const char* label, const uint8_t* data, size_t len) {
    printf("%s=", label);
    for (size_t i = 0; i < len; i++)
        printf("%02X", data[i]);
    printf("\n");
}

static void process_raw(const raw_vector_t* v) {
    uint8_t layer_chain[MAX_PAYLOAD];
    size_t layer_len = llp_build_final_payload(
        layer_chain, sizeof(layer_chain), v->data, v->len);

    uint8_t frame[LLP_MAX_FRAME_SIZE(layer_len)];
    size_t frame_len = llp_build_frame(frame, sizeof(frame),
                                        layer_chain, (uint16_t)layer_len);

    printf("VECTOR: %s\n", v->name);
    printf("desc=%s\n", v->desc);
    print_hex("raw", v->data, v->len);
    print_hex("layer_chain", layer_chain, layer_len);
    print_hex("frame", frame, frame_len);
    printf("---\n");
}

static void process_layer(const layer_vector_t* v) {
    uint8_t frame[LLP_MAX_FRAME_SIZE(v->chain_len)];
    size_t frame_len = llp_build_frame(frame, sizeof(frame),
                                        v->chain, v->chain_len);

    printf("VECTOR: %s\n", v->name);
    printf("desc=%s\n", v->desc);
    print_hex("layer_chain", v->chain, v->chain_len);
    print_hex("frame", frame, frame_len);
    printf("---\n");
}

int main(void) {
    /* =================================================================
     * RAW vectors: raw application data → llp_build_final_payload → frame
     * ================================================================= */

    const uint8_t empty[]          = {};
    const uint8_t single_42[]      = {0x42};
    const uint8_t hello[]          = {'H','e','l','l','o'};
    const uint8_t null_byte[]      = {0x00};
    const uint8_t ff_byte[]        = {0xFF};
    const uint8_t aa_byte[]        = {0xAA};
    const uint8_t aa55[]           = {0xAA, 0x55};
    const uint8_t triple_aa[]      = {0xAA, 0xAA, 0xAA};
    const uint8_t mixed_aa[]       = {0x01, 0xAA, 0x02, 0xAA, 0x03};
    const uint8_t zeros_16[]       = {0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0};
    const uint8_t ones_16[]        = {1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1};
    const uint8_t inc_16[]         = {0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15};
    const uint8_t all_ff_16[]      = {0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,
                                      0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF};
    const uint8_t aa_prefix[]      = {0xAA, 0x42};
    const uint8_t aa_suffix[]      = {0x42, 0xAA};
    const uint8_t aa_boundary[]    = {0xAA, 0xAA, 0x00, 0xAA};
    const uint8_t alternating[]    = {0xAA, 0x00, 0xAA, 0x00, 0xAA};
    const uint8_t seq_32[]         = {0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,
                                      16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31};

    raw_vector_t raw_vectors[] = {
        {"empty_payload",      empty,      0, "Empty application payload (FinalNode only)"},
        {"single_byte_42",     single_42,  1, "Single byte payload 0x42"},
        {"hello_world",        hello,      5, "5-byte ASCII payload 'Hello'"},
        {"payload_null_byte",  null_byte,  1, "Payload containing 0x00"},
        {"payload_ff_byte",    ff_byte,    1, "Payload containing 0xFF"},
        {"payload_aa_byte",    aa_byte,    1, "Payload containing single 0xAA (tests stuffing)"},
        {"payload_aa55",       aa55,       2, "Payload containing 0xAA 0x55 (tests magic overlap)"},
        {"payload_triple_aa",  triple_aa,  3, "Payload with three consecutive 0xAA"},
        {"payload_mixed_aa",   mixed_aa,   5, "Payload with scattered 0xAA bytes"},
        {"payload_zeros_16",   zeros_16,  16, "16-byte payload of all zeros"},
        {"payload_ones_16",    ones_16,   16, "16-byte payload of all 0x01"},
        {"payload_incremental",inc_16,    16, "Sequential bytes 0..15"},
        {"payload_all_ff_16",  all_ff_16, 16, "16-byte payload of all 0xFF"},
        {"payload_aa_prefix",  aa_prefix,  2, "0xAA at start of payload"},
        {"payload_aa_suffix",  aa_suffix,  2, "0xAA at end of payload"},
        {"payload_aa_boundary",aa_boundary,4,"0xAA boundaries with 0x00 interleaved"},
        {"payload_alternating",alternating,5,"Alternating 0xAA 0x00"},
        {"payload_seq_32",     seq_32,    32, "32 sequential bytes"},
    };

    size_t n_raw = sizeof(raw_vectors) / sizeof(raw_vectors[0]);
    printf("=== RAW VECTORS ===\n");
    for (size_t i = 0; i < n_raw; i++)
        process_raw(&raw_vectors[i]);

    /* =================================================================
     * LAYER vectors: pre-built layer chains → llp_build_frame
     * ================================================================= */

    /* Layer chain format: [LAYER_ID][META_LEN][METADATA...]...[0x00][RAW...] */

    /* Layer header helpers */
    /* Single layer header: id(1) + meta_len(1) + metadata(N) */
    #define LAYER_HDR(id, meta)    (id), (uint8_t)(meta)
    #define META_BYTES(...)        __VA_ARGS__

    /* Passthrough layer with ID 0x01 and 3 bytes of metadata */
    const uint8_t pt_layer_1[] = {
        0x01, 0x03, 0x10, 0x20, 0x30,  /* layer 0x01, meta_len=3 */
        0x00,                           /* FinalNode */
        'H', 'e', 'l', 'l', 'o'        /* raw data */
    };
    const uint8_t pt_layer_2[] = {
        0x01, 0x01, 0xAA,              /* layer 0x01, meta_len=1, meta=0xAA */
        0x02, 0x02, 0xBB, 0xCC,       /* layer 0x02, meta_len=2, meta=0xBB,0xCC */
        0x00,                          /* FinalNode */
        0x42                           /* raw data: 0x42 */
    };
    /* Transform layer (0x80) */
    const uint8_t tf_layer[] = {
        0x80, 0x04, 0xDE, 0xAD, 0xBE, 0xEF,  /* transform layer, meta_len=4 */
        0x00,                                   /* FinalNode */
        'O', 'K'                                /* raw data */
    };
    /* Mixed passthrough + transform */
    const uint8_t mixed_layers[] = {
        0x01, 0x02, 0x11, 0x22,               /* passthrough */
        0x81, 0x01, 0xFF,                      /* transform */
        0x00,                                  /* FinalNode */
        0x55, 0xAA, 0x01                       /* raw data */
    };
    /* Unknown layer ID 0xFF */
    const uint8_t unknown_layer[] = {
        0xFF, 0x01, 0x00,                      /* unknown layer ID 0xFF */
        0x00,                                  /* FinalNode */
        'd', 'a', 't', 'a'
    };
    /* Passthrough with extended metadata (>= 255 bytes) */
    /* We'll create a simpler version: 2 passthrough layers with small metadata */
    const uint8_t empty_layer_chain[] = {
        0x00  /* FinalNode only, no raw data */
    };
    /* Layer 0x7F (max passthrough ID) */
    const uint8_t max_passthrough[] = {
        0x7F, 0x02, 0xF0, 0x0F,
        0x00,
        'x', 'y', 'z'
    };
    /* Layer 0xFE (max transform ID) */
    const uint8_t max_transform[] = {
        0xFE, 0x01, 0xA5,
        0x00,
        0x01, 0x02, 0x03
    };
    /* Nested layers: 3 passthrough layers deep */
    const uint8_t three_layers[] = {
        0x01, 0x01, 0x01,
        0x02, 0x01, 0x02,
        0x03, 0x01, 0x03,
        0x00,
        'd', 'e', 'e', 'p'
    };
    /* Layer with metadata containing 0xAA (stuffing in metadata) */
    const uint8_t stuffing_metadata[] = {
        0x01, 0x04, 0xAA, 0x00, 0xAA, 0x55,
        0x00,
        'O', 'K'
    };
    /* Passthrough with meta_len = 0 */
    const uint8_t zero_meta_len[] = {
        0x01, 0x00,
        0x00,
        'd', 'a', 't', 'a'
    };
    /* Four passthrough layers */
    const uint8_t four_layers[] = {
        0x01, 0x00,
        0x02, 0x00,
        0x03, 0x00,
        0x04, 0x00,
        0x00,
        'e', 'n', 'd'
    };

    layer_vector_t layer_vectors[] = {
        {"layer_empty_chain",       empty_layer_chain, sizeof(empty_layer_chain),
         "Only FinalNode, no raw data (layer chain = [0x00])"},
        {"layer_single_passthrough",pt_layer_1, sizeof(pt_layer_1),
         "Single passthrough layer (0x01) with metadata + FinalNode + 'Hello'"},
        {"layer_two_passthrough",   pt_layer_2, sizeof(pt_layer_2),
         "Two passthrough layers (0x01, 0x02) with metadata"},
        {"layer_transform",         tf_layer, sizeof(tf_layer),
         "Single transform layer (0x80) with 4-byte metadata"},
        {"layer_mixed",             mixed_layers, sizeof(mixed_layers),
         "Passthrough (0x01) then transform (0x81) then FinalNode"},
        {"layer_unknown_id",        unknown_layer, sizeof(unknown_layer),
         "Unknown layer ID (0xFF) with metadata"},
        {"layer_max_passthrough",   max_passthrough, sizeof(max_passthrough),
         "Max passthrough layer ID (0x7F) with metadata"},
        {"layer_max_transform",     max_transform, sizeof(max_transform),
         "Max transform layer ID (0xFE) with metadata"},
        {"layer_three_nested",      three_layers, sizeof(three_layers),
         "Three nested passthrough layers before FinalNode"},
        {"layer_stuffing_metadata", stuffing_metadata, sizeof(stuffing_metadata),
         "Layer metadata containing 0xAA bytes (stuffing test)"},
        {"layer_zero_meta_len",     zero_meta_len, sizeof(zero_meta_len),
         "Passthrough layer with meta_len=0"},
        {"layer_four_nested",       four_layers, sizeof(four_layers),
         "Four nested passthrough layers before FinalNode"},
    };

    size_t n_layer = sizeof(layer_vectors) / sizeof(layer_vectors[0]);
    printf("\n=== LAYER VECTORS ===\n");
    for (size_t i = 0; i < n_layer; i++)
        process_layer(&layer_vectors[i]);

    return 0;
}
