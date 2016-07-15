#include "DirectUI.h"

namespace DirectUI
{
	NativeHWNDHost::NativeHWNDHost(const NativeHWNDHost &)
	{
	}
	NativeHWNDHost::NativeHWNDHost()
	{
	}
	NativeHWNDHost::~NativeHWNDHost()
	{
	}
	LRESULT NativeHWNDHost::WndProc(HWND, UINT, WPARAM, LPARAM)
	{
		return LRESULT();
	}
	NativeHWNDHost & NativeHWNDHost::operator=(const NativeHWNDHost &)
	{
		// TODO: 在此处插入 return 语句
		return *this;
	}
	UINT NativeHWNDHost::AsyncDestroyMsg()
	{
		return 0;
	}
	HRESULT NativeHWNDHost::Create(unsigned short const * lpClassName, unsigned short const * lpWindowName, HWND hWndParent, HICON hIcon, int x, int y, int nWidth, int nHeight, int dwExStyle, int dwStyle, HINSTANCE, UINT, NativeHWNDHost ** out)
	{
		return E_NOTIMPL;
	}
	HRESULT NativeHWNDHost::Create(unsigned short const * lpWindowName, HWND hWndParent, HICON hIcon, int x, int y, int nWidth, int nHeight, int dwExStyle, int dwStyle, unsigned int, NativeHWNDHost ** out)
	{
		return E_NOTIMPL;
	}
	void NativeHWNDHost::Destroy()
	{
	}
	void NativeHWNDHost::DestroyWindow()
	{
	}
	Element * NativeHWNDHost::GetElement()
	{
		return nullptr;
	}
	HWND NativeHWNDHost::GetHWND()
	{
		return HWND();
	}
	void NativeHWNDHost::HideWindow()
	{
	}
	void NativeHWNDHost::Host(Element *)
	{
	}
	HRESULT NativeHWNDHost::Initialize(unsigned short const * lpClassName, unsigned short const * lpWindowName, HWND hWndParent, HICON hIcon, int x, int y, int nWidth, int nHeight, int dwExStyle, int dwStyle, HINSTANCE, UINT)
	{
		return E_NOTIMPL;
	}
	HRESULT NativeHWNDHost::Initialize(const unsigned short *, HWND, HICON, int, int, int, int, int, int, UINT)
	{
		return E_NOTIMPL;
	}
	HRESULT NativeHWNDHost::OnMessage(UINT uMsg, WPARAM wParam, LPARAM lParam, LRESULT *)
	{
		return E_NOTIMPL;
	}
	int NativeHWNDHost::RestoreFocus()
	{
		return 0;
	}
	void NativeHWNDHost::SaveFocus()
	{
	}
	void NativeHWNDHost::SetDefaultFocusID(const unsigned short *)
	{
	}
	void NativeHWNDHost::ShowWindow(int)
	{
	}
}