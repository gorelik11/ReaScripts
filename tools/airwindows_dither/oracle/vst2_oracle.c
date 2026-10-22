// Verification-only VST2 host: loads an installed Airwindows .vst bundle and
// runs it through processDoubleReplacing, so libawdither can be compared
// bit-for-bit against the exact binary REAPER loads, without REAPER.
//
// usage: vst2_oracle <bundle.vst> <samplerate> <seed> <in.f64> <out.f64> [param=value ...]
// in/out: raw interleaved stereo float64. Seed goes to srand() before the
// plugin is constructed, matching aw_create().
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct AEffect AEffect;
typedef intptr_t (*HostCallback)(AEffect*, int32_t, int32_t, intptr_t, void*, float);
struct AEffect {
	int32_t magic;
	intptr_t (*dispatcher)(AEffect*, int32_t, int32_t, intptr_t, void*, float);
	void (*process)(AEffect*, float**, float**, int32_t);
	void (*setParameter)(AEffect*, int32_t, float);
	float (*getParameter)(AEffect*, int32_t);
	int32_t numPrograms, numParams, numInputs, numOutputs, flags;
	intptr_t resvd1, resvd2;
	int32_t initialDelay, realQualities, offQualities;
	float ioRatio;
	void* object;
	void* user;
	int32_t uniqueID, version;
	void (*processReplacing)(AEffect*, float**, float**, int32_t);
	void (*processDoubleReplacing)(AEffect*, double**, double**, int32_t);
	char future[56];
};
enum { effOpen = 0, effClose = 1, effSetSampleRate = 10, effSetBlockSize = 11, effMainsChanged = 12 };
enum { effFlagsCanDoubleReplacing = 1 << 12 };
#define BLOCK 512

static intptr_t host(AEffect* e, int32_t op, int32_t idx, intptr_t v, void* p, float o)
{
	return op == 1 ? 2400 : 0; // audioMasterVersion
}

int main(int argc, char** argv)
{
	if (argc < 6) { fprintf(stderr, "usage: %s bundle sr seed in out [i=v ...]\n", argv[0]); return 2; }
	const char* bundle = argv[1];
	const char* base = strrchr(bundle, '/');
	char name[256], path[1024];
	snprintf(name, sizeof name, "%s", base ? base + 1 : bundle);
	*strstr(name, ".vst") = 0;
	snprintf(path, sizeof path, "%s/Contents/MacOS/%s", bundle, name);
	void* lib = dlopen(path, RTLD_NOW | RTLD_LOCAL);
	if (!lib) { fprintf(stderr, "dlopen: %s\n", dlerror()); return 1; }
	AEffect* (*entry)(HostCallback) = (AEffect* (*)(HostCallback))dlsym(lib, "VSTPluginMain");
	if (!entry) entry = (AEffect* (*)(HostCallback))dlsym(lib, "main_macho");
	if (!entry) { fprintf(stderr, "no VST entry point\n"); return 1; }

	srand((unsigned)strtoul(argv[3], NULL, 10));
	AEffect* fx = entry(host);
	if (!fx || fx->magic != 0x56737450) { fprintf(stderr, "not a VST2 plugin\n"); return 1; }
	if (!(fx->flags & effFlagsCanDoubleReplacing)) { fprintf(stderr, "no double processing\n"); return 1; }
	fx->dispatcher(fx, effOpen, 0, 0, NULL, 0);
	fx->dispatcher(fx, effSetSampleRate, 0, 0, NULL, (float)atof(argv[2]));
	fx->dispatcher(fx, effSetBlockSize, 0, BLOCK, NULL, 0);
	for (int i = 6; i < argc; i++) {
		int idx; float val;
		if (sscanf(argv[i], "%d=%f", &idx, &val) != 2) { fprintf(stderr, "bad param %s\n", argv[i]); return 2; }
		fx->setParameter(fx, idx, val);
	}
	fx->dispatcher(fx, effMainsChanged, 0, 1, NULL, 0);

	FILE* fin = fopen(argv[4], "rb");
	FILE* fout = fopen(argv[5], "wb");
	if (!fin || !fout) { perror("open"); return 1; }
	double inter[BLOCK * 2], inL[BLOCK], inR[BLOCK], outL[BLOCK], outR[BLOCK];
	double* ins[2] = {inL, inR};
	double* outs[2] = {outL, outR};
	size_t got;
	while ((got = fread(inter, sizeof(double) * 2, BLOCK, fin)) > 0) {
		for (size_t i = 0; i < got; i++) { inL[i] = inter[2 * i]; inR[i] = inter[2 * i + 1]; }
		fx->processDoubleReplacing(fx, ins, outs, (int32_t)got);
		for (size_t i = 0; i < got; i++) { inter[2 * i] = outL[i]; inter[2 * i + 1] = outR[i]; }
		fwrite(inter, sizeof(double) * 2, got, fout);
	}
	fclose(fin);
	fclose(fout);
	fx->dispatcher(fx, effMainsChanged, 0, 0, NULL, 0);
	fx->dispatcher(fx, effClose, 0, 0, NULL, 0);
	return 0;
}
