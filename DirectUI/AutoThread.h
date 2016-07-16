#pragma once

namespace DirectUI
{
	class AutoThread
	{
	public:
		AutoThread();
		~AutoThread();
		AutoThread& operator=(const AutoThread &);
		HRESULT Init();
	};
}