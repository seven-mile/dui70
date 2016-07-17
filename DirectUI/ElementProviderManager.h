#pragma once

namespace DirectUI
{
	class UILIB_API ElementProviderManager
	{
	public:
		ElementProviderManager & __thiscall operator=(class DirectUI::ElementProviderManager const &);

		static unsigned long Add(ElementProvider *);
		static void __stdcall Close();
		static ElementProvider *__stdcall Find(Element *);
		static bool __stdcall FindProviderCallback(ElementProvider *, void *);
		static unsigned long __stdcall Init();
		static void __stdcall Remove(ElementProvider *);
	};
}