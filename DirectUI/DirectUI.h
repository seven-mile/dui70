#pragma once
#include <Windows.h>
#include <oleacc.h>
#include <objbase.h>
#include <initguid.h>
#include <oleacc.h>
#include <Commctrl.h>

#if	defined(DIRECTUI_EXPORTS)
#define UILIB_API __declspec(dllexport)
#else
#define UILIB_API 
#endif

#include "types.h"
#include "misc.h"
#include "Value.h"

#include "AutoLock.h"
#include "AutoThread.h"
#include "AutoVariant.h"
#include "Interfaces.h"
#include "Primitives.h"
#include "element.h"

#include "Browser.h"
#include "Bind.h"
#include "AnimationStrip.h"
#include "Button.h"
#include "base.h"
#include "AccessibleButton.h"
#include "AutoButton.h"
#include "event.h"
#include "layout.h"
#include "BorderLayout.h"
#include "host.h"
#include "accessibility.h"
#include "parser.h"
#include "provider.h"

#include "Movie.h"
#include "ElementWithHWND.h"
#include "HWNDElement.h"
#include "NativeHWNDHost.h"
#include "HWNDHost.h"
#include "CBase.h"
#include "CAVI.h"
#include "CPushButton.h"
#include "CBaseCheckRadioButton.h"
#include "CBaseScrollBar.h"
#include "CHScrollBar.h"
#include "CCheckBox.h"
#include "CCommandLink.h"
#include "CListBox.h"
#include "CListView.h"
#include "CProgressBar.h"
#include "CRadioButton.h"
#include "CCSysLink.h"
#include "CTrackBar.h"
#include "CTreeView.h"
#include "CVScrollBar.h"
#include "CallstackTracker.h"
#include "CheckBoxGlyph.h"
#include "Expandable.h"
#include "Clipper.h"
#include "Combobox.h"

namespace DirectUI
{
	UILIB_API HRESULT WINAPI InitProcessPriv(int duiVersion, unsigned short*unk1, char unk2, bool bEnableUIAutomationProvider);
	UILIB_API HRESULT WINAPI UnInitProcessPriv(unsigned short*unk1);
	UILIB_API HRESULT WINAPI InitThread(int iDontKnow);
	UILIB_API void WINAPI UnInitThread();

	UILIB_API int WINAPI CreateDUIWrapper(Element*,class XProvider**);
	UILIB_API int WINAPI CreateDUIWrapperEx(Element*, class IXProviderCP*, class XProvider**);
	UILIB_API int WINAPI CreateDUIWrapperFromResource(HINSTANCE,UCString, UCString, UCString, class XResourceProvider**);

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


	UILIB_API ATOM WINAPI StrToID(UCString resId);


	UILIB_API int WINAPI UnicodeToMultiByte(UCString lpWideCharStr, int cchWideChar, int unk);
	UILIB_API int WINAPI MultiByteToUnicode(LPCSTR lpMultiByteStr, int cbMultiByte, int unk);

	UILIB_API BOOL WINAPI IsAnimationsEnabled();
	UILIB_API int WINAPI IsPalette(HWND hWnd);
	UILIB_API BOOL WINAPI IsUIAutomationProviderEnabled();

	UILIB_API int WINAPI DUIDrawShadowText(HDC hdcDest, UCString lpchText, int cchText, LPRECT hdcSrc, UINT format, COLORREF color);
}