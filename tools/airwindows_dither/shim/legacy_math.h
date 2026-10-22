// Pre-2011 C++ <math.h> semantics for Ditherbox2018. Its original Intel
// binary was built against headers with no long double overloads, so every
// math call converted its long double argument to double and returned double
// (the binary imports _floor, _sin, _cos ... never the *l variants). Modern
// libc++ would pick floorl/sinl/cosl instead and change the output.
#include <math.h>
#include <set>
#include <string>

#define floor(x) (::floor((double)(x)))
#define ceil(x) (::ceil((double)(x)))
#define sin(x) (::sin((double)(x)))
#define cos(x) (::cos((double)(x)))
#define fmod(x, y) (::fmod((double)(x), (double)(y)))
#define pow(x, y) (::pow((double)(x), (double)(y)))
#define log10(x) (::log10((double)(x)))
#define fabs(x) (::fabs((double)(x)))
