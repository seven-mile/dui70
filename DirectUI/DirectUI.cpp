#include "DirectUI.h"

namespace DirectUI
{
	UILIB_API HRESULT WINAPI InitProcessPriv(int duiVersion, unsigned short*unk1, char unk2, bool bEnableUIAutomationProvider)
	{
		return 0;
	}

	UILIB_API HRESULT WINAPI UnInitProcessPriv(unsigned short*unk1)
	{
		return 0;
	}
	UILIB_API HRESULT WINAPI InitThread(int iDontKnow)
	{
		return 0;
	}
	UILIB_API void WINAPI UnInitThread()
	{
		return;
	}

	// These might be wrong, disassemble and check if it is DirectUI::XProvider* or DirectUI::XProvider**
	UILIB_API int WINAPI CreateDUIWrapper(Element*, class XProvider*)
	{
		return 0;
	}
	UILIB_API int WINAPI CreateDUIWrapperEx(Element*, class IXProviderCP*, class XProvider*)
	{
		return 0;
	}
	UILIB_API int WINAPI CreateDUIWrapperFromResource(HINSTANCE, unsigned short*, unsigned short*, unsigned short*, class XResourceProvider*)
	{
		return 0;
	}

	UILIB_API int WINAPI GetScreenDPI()
	{
		return 0;
	}

	UILIB_API int WINAPI RegisterAllControls()
	{
		return 0;
	}

	UILIB_API int WINAPI RegisterBaseControls()
	{
		return 0;
	}

	UILIB_API int WINAPI RegisterBrowserControls()
	{
		return 0;
	}

	UILIB_API int WINAPI RegisterCommonControls()
	{
		return 0;
	}

	UILIB_API int WINAPI RegisterExtendedControls()
	{
		return 0;
	}

	UILIB_API int WINAPI RegisterMacroControls()
	{
		return 0;
	}

	UILIB_API int WINAPI RegisterMiscControls()
	{
		return 0;
	}

	UILIB_API int WINAPI RegisterStandardControls()
	{
		return 0;
	}

	UILIB_API int WINAPI RegisterXControls()
	{
		return 0;
	}

	UILIB_API int WINAPI StartMessagePump()
	{
		return 0;
	}

	UILIB_API int WINAPI StopMessagePump()
	{
		return 0;
	}


	UILIB_API ATOM WINAPI StrToID(LPCWSTR resId)
	{
		return 0;
	}


	UILIB_API int WINAPI UnicodeToMultiByte(LPCWSTR lpWideCharStr, int cchWideChar, int unk)
	{
		return 0;
	}
	UILIB_API int WINAPI MultiByteToUnicode(LPCSTR lpMultiByteStr, int cbMultiByte, int unk)
	{
		return 0;
	}

	UILIB_API BOOL WINAPI IsAnimationsEnabled()
	{
		return 0;
	}
	UILIB_API int WINAPI IsPalette(HWND hWnd)
	{
		return 0;
	}
	UILIB_API BOOL WINAPI IsUIAutomationProviderEnabled()
	{
		return 0;
	}
}