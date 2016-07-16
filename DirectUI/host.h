#pragma once

#include "types.h"
//#include "Element.h"

namespace DirectUI
{
	class XHost
	{
	public:

		XHost();
		~XHost();
		XHost & operator=(XHost const &);

		static long Create(class IXElementCP*, XHost**);
		void Destroy();
		void DestroyWindow();

		class Element* GetElement();
		HWND GetHWND();

		void HideWindow();
		void Host(class Element*);
		long Initialize(class IXElementCP*);
		void ShowWindow(int);

		static LRESULT WndProc(HWND hwnd, UINT uMsg, WPARAM wParam, LPARAM lParam);
	};
}