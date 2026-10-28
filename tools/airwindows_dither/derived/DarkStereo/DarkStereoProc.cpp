/* ========================================
 *  DarkStereo - derived from Airwindows Dark (MIT license, see
 *  vendor/LICENSE-airwindows.txt).
 *
 *  Dark picks, for each sample and each channel on its own, whichever of the
 *  two neighbouring levels best continues the recent slew of its output.
 *  On centred material both channels then make the same choices, so the
 *  error is common to L and R and collapses the image toward the centre.
 *
 *  DarkStereo picks the L and R levels together, from the four pairs, with
 *  Dark's own cost per channel plus lambda * errL * errR: a pair whose errors
 *  share a sign costs more. Where Dark's choice is clear nothing changes;
 *  near-ties split between the channels. C = 0 is Dark, bit for bit.
 *  lambda = 2 * C. Dark's own margin is almost always a full LSB (its slew
 *  prediction usually lies outside the two candidates), so nothing changes
 *  below C = 0.5; C = 0.55 brings the overall L/R error correlation to ~0.
 *  (A penalty on the error band-passed at 900 Hz was tried: it fed back into
 *  a +6..12 dB resonance there.)
 *
 *  Known limit (2026-10-28, master 1 Artur): the flips land mostly in the
 *  highs; Dark's mid-band error is a deterministic shadow of the (mostly
 *  centred) music and stays correlated (+0.53 -> +0.30). Decorrelation then
 *  comes and goes with the material: the error's mid-band width wanders at
 *  0.5..10 Hz more than Dark's (0.200 vs 0.157), heard as tape-like
 *  floating. Tried and dropped: steering lambda from the running L/R
 *  correlation (wander 0.187), different slew depths per channel (mid
 *  correlation barely moves, L/R voicing splits by up to 5 dB).
 * ======================================== */

#ifndef __DarkStereo_H
#include "DarkStereo.h"
#endif

void DarkStereo::processReplacing(float **inputs, float **outputs, VstInt32 sampleFrames)
{
	double inL[512], inR[512], outL[512], outR[512];
	double* ins[2] = {inL, inR};
	double* outs[2] = {outL, outR};
	for (VstInt32 done = 0; done < sampleFrames; ) {
		VstInt32 n = sampleFrames - done < 512 ? sampleFrames - done : 512;
		for (VstInt32 i = 0; i < n; i++) { inL[i] = inputs[0][done + i]; inR[i] = inputs[1][done + i]; }
		processDoubleReplacing(ins, outs, n);
		for (VstInt32 i = 0; i < n; i++) { outputs[0][done + i] = (float)outL[i]; outputs[1][done + i] = (float)outR[i]; }
		done += n;
	}
}

void DarkStereo::processDoubleReplacing(double **inputs, double **outputs, VstInt32 sampleFrames)
{
	double* in1  =  inputs[0];
	double* in2  =  inputs[1];
	double* out1 = outputs[0];
	double* out2 = outputs[1];

	double overallscale = 1.0;
	overallscale /= 44100.0;
	overallscale *= getSampleRate();
	int depth = (int)(17.0*overallscale);
	if (depth < 3) depth = 3;
	if (depth > 98) depth = 98;

	int processing = (VstInt32)( A * 1.999 );
	bool highres = false;
	if (processing == 1) highres = true;
	float scaleFactor;
	if (highres) scaleFactor = 8388608.0;
	else scaleFactor = 32768.0;
	float derez = B;
	if (derez > 0.0) scaleFactor *= pow(1.0-derez,6);
	if (scaleFactor < 0.0001) scaleFactor = 0.0001;
	float outScale = scaleFactor;
	if (outScale < 8.0) outScale = 8.0;
	double lambda = 2.0 * C;

	while (--sampleFrames >= 0)
	{
		double inputSampleL = *in1;
		double inputSampleR = *in2;
		if (fabs(inputSampleL)<1.18e-23) inputSampleL = fpdL * 1.18e-17;
		fpdL ^= fpdL << 13; fpdL ^= fpdL >> 17; fpdL ^= fpdL << 5;
		if (fabs(inputSampleR)<1.18e-23) inputSampleR = fpdR * 1.18e-17;
		fpdR ^= fpdR << 13; fpdR ^= fpdR >> 17; fpdR ^= fpdR << 5;

		inputSampleL *= scaleFactor;
		inputSampleR *= scaleFactor;

		// Dark's two candidates and its cost for each, per channel, unchanged
		int quantAL = floor(inputSampleL);
		int quantBL = floor(inputSampleL+1.0);
		float expectedSlew = 0;
		for(int x = 0; x < depth; x++) expectedSlew += (lastSampleL[x+1] - lastSampleL[x]);
		expectedSlew /= depth;
		float testAL = fabs((lastSampleL[0] - quantAL) - expectedSlew);
		float testBL = fabs((lastSampleL[0] - quantBL) - expectedSlew);

		int quantAR = floor(inputSampleR);
		int quantBR = floor(inputSampleR+1.0);
		expectedSlew = 0;
		for(int x = 0; x < depth; x++) expectedSlew += (lastSampleR[x+1] - lastSampleR[x]);
		expectedSlew /= depth;
		float testAR = fabs((lastSampleR[0] - quantAR) - expectedSlew);
		float testBR = fabs((lastSampleR[0] - quantBR) - expectedSlew);

		bool pickAL = testAL < testBL;
		bool pickAR = testAR < testBR;
		if (lambda > 0.0) {
			// joint choice: Dark's costs plus a penalty on errors of the same sign
			double eAL = quantAL - inputSampleL, eBL = quantBL - inputSampleL;
			double eAR = quantAR - inputSampleR, eBR = quantBR - inputSampleR;
			double cost[4] = {
				(double)testAL + testAR + lambda * eAL * eAR,
				(double)testAL + testBR + lambda * eAL * eBR,
				(double)testBL + testAR + lambda * eBL * eAR,
				(double)testBL + testBR + lambda * eBL * eBR};
			int best = 0;
			for (int k = 1; k < 4; k++) if (cost[k] < cost[best]) best = k;
			pickAL = best < 2;
			pickAR = (best % 2) == 0;
		}
		inputSampleL = pickAL ? quantAL : quantBL;
		inputSampleR = pickAR ? quantAR : quantBR;

		for(int x = depth; x >=0; x--) lastSampleL[x+1] = lastSampleL[x];
		lastSampleL[0] = inputSampleL;
		for(int x = depth; x >=0; x--) lastSampleR[x+1] = lastSampleR[x];
		lastSampleR[0] = inputSampleR;

		inputSampleL /= outScale;
		inputSampleR /= outScale;

		*out1 = inputSampleL;
		*out2 = inputSampleR;

		in1++;
		in2++;
		out1++;
		out2++;
	}
}
