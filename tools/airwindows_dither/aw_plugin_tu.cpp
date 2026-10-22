// One translation unit per plugin (build.sh sets AW_PLUGIN): the vendored
// sources share global names like kParamA, so they cannot meet in one TU.
#define AW_STR2(x) #x
#define AW_STR(x) AW_STR2(x)
#define AW_CAT2(a, b) a##b
#define AW_CAT(a, b) AW_CAT2(a, b)

#include <new>
#define createEffectInstance AW_CAT(createEffectInstance_, AW_PLUGIN)
#include AW_STR(AW_PLUGIN.cpp)
#include AW_STR(AW_CAT(AW_PLUGIN, Proc.cpp))

// Construct into pre-filled memory: some plugins (Ditherbox) never initialise
// their noise state, so whatever the allocation held becomes the dither seed.
AudioEffect* AW_CAT(aw_new_, AW_PLUGIN)(void (*fill)(void*, size_t, unsigned), unsigned seed)
{
	void* mem = ::operator new(sizeof(AW_PLUGIN));
	fill(mem, sizeof(AW_PLUGIN), seed);
	return new (mem) AW_PLUGIN(NULL);
}
void AW_CAT(aw_set_, AW_PLUGIN)(AudioEffect* fx, VstInt32 i, float v) { static_cast<AW_PLUGIN*>(fx)->setParameter(i, v); }
void AW_CAT(aw_proc_, AW_PLUGIN)(AudioEffect* fx, double** in, double** out, VstInt32 n) { static_cast<AW_PLUGIN*>(fx)->processDoubleReplacing(in, out, n); }
