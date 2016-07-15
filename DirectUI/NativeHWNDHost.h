#pragma once
#include "types.h"

namespace DirectUI
{

	class UILIB_API NativeHWNDHost
	{
	public:
		NativeHWNDHost(const NativeHWNDHost&);
		NativeHWNDHost();
		virtual ~NativeHWNDHost();

		static LRESULT WINAPI WndProc(HWND, UINT, WPARAM, LPARAM);
		NativeHWNDHost& operator=(const NativeHWNDHost&);
		static UINT AsyncDestroyMsg();

		static HRESULT WINAPI Create(unsigned short const * lpClassName, unsigned short const * lpWindowName, HWND hWndParent, HICON hIcon, int x, int y, int nWidth, int nHeight, int dwExStyle, int dwStyle, HINSTANCE, UINT, NativeHWNDHost **out);
		static HRESULT WINAPI Create(unsigned short const * lpWindowName, HWND hWndParent, HICON hIcon, int x, int y, int nWidth, int nHeight, int dwExStyle, int dwStyle, unsigned int, NativeHWNDHost **out);

		void Destroy();
		void DestroyWindow();

		class Element* GetElement();
		HWND GetHWND();

		void HideWindow();
		void Host(class Element *);

		HRESULT Initialize(unsigned short const * lpClassName, unsigned short const * lpWindowName, HWND hWndParent, HICON hIcon, int x, int y, int nWidth, int nHeight, int dwExStyle, int dwStyle, HINSTANCE, UINT);
		HRESULT Initialize(const unsigned short*, HWND, HICON, int, int, int, int, int, int, UINT);

		virtual HRESULT OnMessage(UINT uMsg, WPARAM wParam, LPARAM lParam, LRESULT *);

		int RestoreFocus();
		void SaveFocus();
		void SetDefaultFocusID(const unsigned short*);
		void ShowWindow(int);

	private:
		HWND m_hWnd;
		void *unk2;
		void *unk3;
		void *unk4;
		char unk5;
	};
}