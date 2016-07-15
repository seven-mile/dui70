#pragma once
#include "types.h"


namespace DirectUI
{
	UILIB_API HRESULT WINAPI InitProcessPriv(int duiVersion, unsigned short *unk1, char unk2, bool bEnableUIAutomationProvider);
	UILIB_API HRESULT WINAPI UnInitProcessPriv(unsigned short *unk1);
	UILIB_API HRESULT WINAPI InitThread(int iDontKnow);
	UILIB_API void WINAPI UnInitThread();

	// These might be wrong, disassemble and check if it is DirectUI::XProvider * or DirectUI::XProvider **
	UILIB_API int WINAPI CreateDUIWrapper(Element*,class XProvider *);
	UILIB_API int WINAPI CreateDUIWrapperEx(Element*, class IXProviderCP *, class XProvider *);
	UILIB_API int WINAPI CreateDUIWrapperFromResource(HINSTANCE, unsigned short*, unsigned short*, unsigned short*, class XResourceProvider *);

	UILIB_API int WINAPI GetScreenDPI();

	UILIB_API int WINAPI RegisterAllControls();
	UILIB_API int WINAPI RegisterBaseControls();
	UILIB_API int WINAPI RegisterBrowserControls();
	UILIB_API int WINAPI RegisterCommonControls();
	UILIB_API int WINAPI RegisterExtendedControls();
	UILIB_API int WINAPI RegisterMacroControls();
	UILIB_API int WINAPI RegisterMiscControls();
	UILIB_API int WINAPI RegisterStandardControls();
	UILIB_API int WINAPI RegisterXControls();

	UILIB_API int WINAPI StartMessagePump();
	UILIB_API int WINAPI StopMessagePump();


	UILIB_API ATOM WINAPI StrToID(LPCWSTR resId);


	UILIB_API int WINAPI UnicodeToMultiByte(LPCWSTR lpWideCharStr, int cchWideChar, int unk);
	UILIB_API int WINAPI MultiByteToUnicode(LPCSTR lpMultiByteStr, int cbMultiByte, int unk);

	UILIB_API BOOL WINAPI IsAnimationsEnabled();
	UILIB_API int WINAPI IsPalette(HWND hWnd);
	UILIB_API BOOL WINAPI IsUIAutomationProviderEnabled();
}