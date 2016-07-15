#pragma once
#include "types.h"

namespace DirectUI
{
	class AutoButton
	{
	public:

	};

	class AutoLock
	{
	public:

	};

	class AutoThread
	{
	public:
		AutoThread();
		~AutoThread();
		AutoThread& operator=(AutoThread const &);
		HRESULT Init();

	};

	class AutoVariant
	{
	public:
	};
}