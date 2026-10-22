// Minimal stand-in for the VST2 SDK's audioeffectx.h: just enough of
// AudioEffectX for the unmodified Airwindows sources in vendor/ to compile
// as plain C++ DSP classes. No VST ABI is involved.
#ifndef __audioeffect__
#define __audioeffect__

#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

typedef int32_t VstInt32;
typedef void* audioMasterCallback;
enum VstPlugCategory { kPlugCategEffect = 1 };
enum {
	kVstMaxProgNameLen = 24,
	kVstMaxParamStrLen = 8,
	kVstMaxVendorStrLen = 64,
	kVstMaxProductStrLen = 64,
};

inline char* vst_strncpy(char* dst, const char* src, size_t maxLen)
{
	strncpy(dst, src, maxLen);
	dst[maxLen] = 0;
	return dst;
}

inline void float2string(float value, char* text, VstInt32 maxLen)
{
	snprintf(text, maxLen + 1, "%f", value);
}

class AudioEffect {
public:
	virtual ~AudioEffect() {}
};

class AudioEffectX : public AudioEffect {
public:
	AudioEffectX(audioMasterCallback, VstInt32, VstInt32) : sampleRate(44100.0f) {}
	// float, as in the SDK: plugins see exactly what a VST2 host passes.
	float getSampleRate() { return sampleRate; }
	void setSampleRate(float sr) { sampleRate = sr; }
	void setNumInputs(VstInt32) {}
	void setNumOutputs(VstInt32) {}
	void setUniqueID(VstInt32) {}
	void canProcessReplacing() {}
	void canDoubleReplacing() {}
	void programsAreChunks(bool) {}
protected:
	float sampleRate;
};

#endif
