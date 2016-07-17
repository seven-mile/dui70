#pragma once

namespace DirectUI
{
	class UILIB_API FontCache
	{
	public:
		FontCache(FontCache const &);
		FontCache(void);
		FontCache & operator=(FontCache const &);

		static long __stdcall InitProcess(void);
		static long __stdcall InitThread(void);
		static void __stdcall UninitProcess(void);
		static void __stdcall UninitThread(void);
	};
}