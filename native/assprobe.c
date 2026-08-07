/*
 * assprobe: render an .ass with libass and report the pixels.
 *
 * Prints the bounding box of non-transparent pixels, per rendered layer and in
 * aggregate, and optionally dumps the frame as a PPM.
 *
 *   assprobe script.ass TIME_MS [-o out.ppm|out.pam] [-w 1920] [-h 1080] [-v]
 *
 * A .pam output carries alpha, so the frame can be composited over video by a
 * player or by ffmpeg's overlay filter. Useful because a stock ffmpeg often has
 * no libass and so cannot burn subtitles itself.
 *
 * Boxes are printed as x0 y0 x1 y1 with x1/y1 EXCLUSIVE.
 */
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ass/ass.h>

typedef struct { int x0, y0, x1, y1; long npx; } bbox;

static void bbox_init(bbox *b) { b->x0 = 1 << 30; b->y0 = 1 << 30; b->x1 = -1; b->y1 = -1; b->npx = 0; }
static void bbox_add(bbox *b, int x, int y)
{
    if (x < b->x0) b->x0 = x;
    if (y < b->y0) b->y0 = y;
    if (x + 1 > b->x1) b->x1 = x + 1;
    if (y + 1 > b->y1) b->y1 = y + 1;
    b->npx++;
}
static void bbox_print(const char *tag, bbox *b)
{
    if (b->x1 < 0) { printf("%s empty\n", tag); return; }
    printf("%s x %d..%d (w %d)  y %d..%d (h %d)  px %ld\n",
           tag, b->x0, b->x1 - 1, b->x1 - b->x0, b->y0, b->y1 - 1, b->y1 - b->y0, b->npx);
}

static void msg_cb(int level, const char *fmt, va_list va, void *data)
{
    int verbose = *(int *)data;
    if (level > (verbose ? 6 : 3)) return;
    fprintf(stderr, "[libass %d] ", level);
    vfprintf(stderr, fmt, va);
    fprintf(stderr, "\n");
}

/*
 * --scan N: render t = i*1000+500 for i in 0..N-1 with one renderer, printing
 * one line per frame: i x0 x1 y0 y1 npx. This is the measurement path.
 */
static int scan_mode(ASS_Library *lib, ASS_Renderer *rnd, const char *path, int n, int W, int H)
{
    ASS_Track *track = ass_read_file(lib, (char *)path, NULL);
    if (!track) { fprintf(stderr, "cannot read %s\n", path); return 1; }
    for (int i = 0; i < n; i++) {
        int changed = 0;
        ASS_Image *img = ass_render_frame(rnd, track, (long long)i * 1000 + 500, &changed);
        bbox b;
        bbox_init(&b);
        for (ASS_Image *p = img; p; p = p->next) {
            unsigned a = 0xFF - (p->color & 0xFF);
            if (!a) continue;
            for (int y = 0; y < p->h; y++)
                for (int x = 0; x < p->w; x++)
                    if (p->bitmap[y * p->stride + x])
                        bbox_add(&b, p->dst_x + x, p->dst_y + y);
        }
        if (b.x1 < 0) printf("%d - - - - 0\n", i);
        else printf("%d %d %d %d %d %ld\n", i, b.x0, b.x1 - 1, b.y0, b.y1 - 1, b.npx);
    }
    ass_free_track(track);
    return 0;
}

int main(int argc, char **argv)
{
    if (argc < 3) {
        fprintf(stderr, "usage: %s script.ass TIME_MS [-o out.ppm] [-w W] [-h H] [-v]\n"
                        "       %s script.ass --scan N [-w W] [-h H]\n", argv[0], argv[0]);
        return 2;
    }
    const char *path = argv[1];
    int scan_n = 0;
    if (!strcmp(argv[2], "--scan")) {
        if (argc < 4) { fprintf(stderr, "--scan needs a count\n"); return 2; }
        scan_n = atoi(argv[3]);
    }
    long long t = scan_n ? 0 : atoll(argv[2]);
    const char *out = NULL;
    int W = 1920, H = 1080, verbose = 0;
    for (int i = 3; i < argc; i++) {
        if (!strcmp(argv[i], "-o") && i + 1 < argc) out = argv[++i];
        else if (!strcmp(argv[i], "-w") && i + 1 < argc) W = atoi(argv[++i]);
        else if (!strcmp(argv[i], "-h") && i + 1 < argc) H = atoi(argv[++i]);
        else if (!strcmp(argv[i], "-v")) verbose = 1;
    }

    ASS_Library *lib = ass_library_init();
    if (!lib) { fprintf(stderr, "ass_library_init failed\n"); return 1; }
    ass_set_message_cb(lib, msg_cb, &verbose);
    ass_set_extract_fonts(lib, 1);

    ASS_Renderer *rnd = ass_renderer_init(lib);
    if (!rnd) { fprintf(stderr, "ass_renderer_init failed\n"); return 1; }
    ass_set_frame_size(rnd, W, H);
    ass_set_storage_size(rnd, W, H);
    /* Autodetect picks the platform's own font matcher, which is what the
     * editor's bundled renderer uses too, so fallback choices agree. */
    ass_set_fonts(rnd, NULL, "Sans", ASS_FONTPROVIDER_AUTODETECT, NULL, 1);

    if (scan_n) {
        int rc = scan_mode(lib, rnd, path, scan_n, W, H);
        ass_renderer_done(rnd);
        ass_library_done(lib);
        return rc;
    }

    ASS_Track *track = ass_read_file(lib, (char *)path, NULL);
    if (!track) { fprintf(stderr, "cannot read %s\n", path); return 1; }

    int changed = 0;
    ASS_Image *img = ass_render_frame(rnd, track, t, &changed);

    unsigned char *rgb = calloc((size_t)W * H * 3, 1);
    unsigned char *cov = calloc((size_t)W * H, 1);

    bbox all;
    bbox_init(&all);
    int n = 0;
    for (ASS_Image *p = img; p; p = p->next, n++) {
        bbox b;
        bbox_init(&b);
        unsigned r = (p->color >> 24) & 0xFF, g = (p->color >> 16) & 0xFF,
                 bl = (p->color >> 8) & 0xFF, a = 0xFF - (p->color & 0xFF);
        for (int y = 0; y < p->h; y++) {
            for (int x = 0; x < p->w; x++) {
                unsigned k = p->bitmap[y * p->stride + x];
                if (!k) continue;
                int gx = p->dst_x + x, gy = p->dst_y + y;
                unsigned alpha = k * a / 255;
                if (alpha == 0) continue;
                bbox_add(&b, gx, gy);
                bbox_add(&all, gx, gy);
                if (gx < 0 || gy < 0 || gx >= W || gy >= H) continue;
                size_t o = ((size_t)gy * W + gx) * 3;
                rgb[o + 0] = (rgb[o + 0] * (255 - alpha) + r * alpha) / 255;
                rgb[o + 1] = (rgb[o + 1] * (255 - alpha) + g * alpha) / 255;
                rgb[o + 2] = (rgb[o + 2] * (255 - alpha) + bl * alpha) / 255;
                if (alpha > cov[(size_t)gy * W + gx]) cov[(size_t)gy * W + gx] = alpha;
            }
        }
        char tag[64];
        snprintf(tag, sizeof tag, "img[%02d] color=%08X", n, p->color);
        bbox_print(tag, &b);
    }
    printf("images %d  changed %d\n", n, changed);
    bbox_print("ALL", &all);

    /* Row profile: how many covered pixels per scanline, for reading off the
     * real glyph band without eyeballing a screenshot. */
    printf("rows:");
    for (int y = 0; y < H; y++) {
        long c = 0;
        for (int x = 0; x < W; x++) if (cov[(size_t)y * W + x] > 128) c++;
        if (c) printf(" %d:%ld", y, c);
    }
    printf("\n");

    if (out) {
        size_t n = strlen(out);
        int alpha = n > 4 && !strcmp(out + n - 4, ".pam");
        FILE *f = fopen(out, "wb");
        if (f) {
            if (alpha) {
                fprintf(f, "P7\nWIDTH %d\nHEIGHT %d\nDEPTH 4\nMAXVAL 255\n"
                           "TUPLTYPE RGB_ALPHA\nENDHDR\n", W, H);
                for (size_t i = 0; i < (size_t)W * H; i++) {
                    fwrite(rgb + i * 3, 1, 3, f);
                    fwrite(cov + i, 1, 1, f);
                }
            } else {
                fprintf(f, "P6\n%d %d\n255\n", W, H);
                fwrite(rgb, 1, (size_t)W * H * 3, f);
            }
            fclose(f);
            printf("wrote %s\n", out);
        }
    }

    ass_free_track(track);
    ass_renderer_done(rnd);
    ass_library_done(lib);
    free(rgb);
    free(cov);
    return 0;
}
