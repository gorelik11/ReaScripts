// awproc: runs one vendored Airwindows plugin over raw audio.
//
// usage: awproc <Plugin> <samplerate> <seed> <prefill> [index=value ...]
// stdin/stdout: interleaved stereo float64, native endian. Processing goes
// through each plugin's own processDoubleReplacing, as a VST2 host would.
//
// seed: srand(seed) right before construction. Airwindows seeds its noise
// state from rand() in the constructor (Ditherbox2018 calls rand() while
// processing), so the seed fixes the dither noise.
// prefill: the plugin's memory is filled before construction, because
// Ditherbox never initialises its noise state and inherits whatever the
// allocation held. 0..255 writes that byte everywhere (0 reproduces the
// installed plugin, whose fresh allocation is zeroed: no noise at all);
// -1 fills with noise derived from the seed.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "audioeffectx.h"

#ifdef AW_WITH_2018
#define AW_PLUGINS(X) X(Dark) X(Ditherbox) X(Monitoring) X(TPDFWide) X(NotJustAnotherDither) X(Ditherbox2018)
#else
#define AW_PLUGINS(X) X(Dark) X(Ditherbox) X(Monitoring) X(TPDFWide) X(NotJustAnotherDither)
#endif

// The plugin classes share method names but no common interface, so each
// plugin gets typed trampolines (defined in aw_plugin_tu.cpp).
#define AW_DECLARE(P) \
	AudioEffect* aw_new_##P(void (*)(void*, size_t, unsigned), unsigned); \
	void aw_set_##P(AudioEffect*, VstInt32, float); \
	void aw_proc_##P(AudioEffect*, double**, double**, VstInt32);
AW_PLUGINS(AW_DECLARE)

static int g_prefill = 0;
static void fill_memory(void* mem, size_t n, unsigned seed)
{
	unsigned char* b = (unsigned char*)mem;
	if (g_prefill >= 0) { memset(b, g_prefill, n); return; }
	uint32_t x = seed * 2654435761u + 0x9E3779B9u;
	for (size_t i = 0; i < n; i++) {
		x ^= x << 13; x ^= x >> 17; x ^= x << 5;
		b[i] = (unsigned char)(x >> 24);
	}
}

enum { BLOCK = 512 };

int main(int argc, char** argv)
{
	if (argc < 5) {
		fprintf(stderr, "usage: %s plugin samplerate seed prefill [index=value ...]\n", argv[0]);
		return 2;
	}
	const char* name = argv[1];
	float sampleRate = (float)atof(argv[2]);
	unsigned seed = (unsigned)strtoul(argv[3], NULL, 10);
	g_prefill = atoi(argv[4]);

	AudioEffect* fx = NULL;
	void (*setParam)(AudioEffect*, VstInt32, float) = NULL;
	void (*process)(AudioEffect*, double**, double**, VstInt32) = NULL;
	srand(seed);
#define AW_MATCH(P) \
	if (!fx && strcmp(name, #P) == 0) { \
		fx = aw_new_##P(fill_memory, seed); setParam = aw_set_##P; process = aw_proc_##P; \
	}
	AW_PLUGINS(AW_MATCH)
	if (!fx) { fprintf(stderr, "awproc: unknown plugin %s\n", name); return 2; }
	static_cast<AudioEffectX*>(fx)->setSampleRate(sampleRate);
	for (int i = 5; i < argc; i++) {
		int index;
		float value;
		if (sscanf(argv[i], "%d=%f", &index, &value) != 2) { fprintf(stderr, "awproc: bad parameter %s\n", argv[i]); return 2; }
		setParam(fx, index, value);
	}

	static double inter[BLOCK * 2], inL[BLOCK], inR[BLOCK], outL[BLOCK], outR[BLOCK];
	double* ins[2] = {inL, inR};
	double* outs[2] = {outL, outR};
	size_t got;
	while ((got = fread(inter, sizeof(double) * 2, BLOCK, stdin)) > 0) {
		for (size_t i = 0; i < got; i++) { inL[i] = inter[2 * i]; inR[i] = inter[2 * i + 1]; }
		process(fx, ins, outs, (VstInt32)got);
		for (size_t i = 0; i < got; i++) { inter[2 * i] = outL[i]; inter[2 * i + 1] = outR[i]; }
		if (fwrite(inter, sizeof(double) * 2, got, stdout) != got) { perror("awproc: write"); return 1; }
	}
	return ferror(stdin) ? 1 : 0;
}
