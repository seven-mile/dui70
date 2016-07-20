#pragma once
#include <Windows.h>
#include <oleacc.h>
#include <objbase.h>
#include <initguid.h>
#include <oleacc.h>
#include <Commctrl.h>
#include <UIAutomationCore.h>

#if	defined(DIRECTUI_EXPORTS)
#define UILIB_API __declspec(dllexport)
#else
#define UILIB_API 
#endif

#include "types.h"
#include "misc.h"
#include "Interfaces.h"

#include "AutoLock.h"
#include "AutoThread.h"
#include "AutoVariant.h"
#include "Value.h"

#include "Primitives.h"
#include "parser.h"
#include "element.h"
#include "Browser.h"
#include "Bind.h"
#include "AnimationStrip.h"
#include "Button.h"
#include "base.h"
#include "AccessibleButton.h"
#include "AutoButton.h"
#include "PushButton.h"
#include "event.h"
#include "layout.h"
#include "BorderLayout.h"
#include "host.h"
#include "accessibility.h"
#include "provider.h"
#include "Movie.h"
#include "ElementWithHWND.h"
#include "HWNDElement.h"
#include "DialogElement.h"
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
#include "DuiNavigate.h"
#include "Edit.h"
#include "Element.h"
#include "EventManager.h"
#include "ExpandCollapse.h"
#include "Expando.h"
#include "ExpandoButtonGlyph.h"
#include "FontCache.h"
#include "FontCheckOut.h"
#include "GridItem.h"
#include "Grid.h"
#include "HWNDElement.h"
#include "InvokeHelper.h"
#include "LinkedList.h"
#include "Macro.h"
#include "NavScoring.h"
#include "Navigator.h"
#include "TextGraphic.h"
#include "PText.h"
#include "Page.h"
#include "Progress.h"
#include "RadioButtonGlyph.h"
#include "RangeValue.h"
#include "RefPointElement.h"
#include "RepeatButton.h"
#include "Repeater.h"
#include "ScrollBar.h"
#include "ScrollItem.h"
#include "Scroll.h"
#include "ScrollViewer.h"
#include "SelectionItem.h"
#include "Selection.h"
#include "Selector.h"
#include "SelectorNoDefault.h"
#include "SelectorSelectionItem.h"
#include "SelectorSelection.h"
#include "StyledScrollViewer.h"
#include "TableItem.h"
#include "Table.h"
#include "TaskPage.h"
#include "Thumb.h"
#include "Toggle.h"
#include "UnknownElement.h"
#include "Viewer.h"
#include "XBaby.h"
#include "XElement.h"
#include "XProvider.h"

//UnknownElement

namespace DirectUI
{
	HRESULT WINAPI InitProcessPriv(int duiVersion, unsigned short*unk1, char unk2, bool bEnableUIAutomationProvider);
	HRESULT WINAPI UnInitProcessPriv(unsigned short*unk1);
	HRESULT WINAPI InitThread(int iDontKnow);
	void WINAPI UnInitThread();

	int WINAPI CreateDUIWrapper(Element*,class XProvider**);
	int WINAPI CreateDUIWrapperEx(Element*, class IXProviderCP*, class XProvider**);
	int WINAPI CreateDUIWrapperFromResource(HINSTANCE,UCString, UCString, UCString, class XResourceProvider**);

	int WINAPI GetScreenDPI();

	int WINAPI RegisterAllControls();
	int WINAPI RegisterBaseControls();
	int WINAPI RegisterBrowserControls();
	int WINAPI RegisterCommonControls();
	int WINAPI RegisterExtendedControls();
	int WINAPI RegisterMacroControls();
	int WINAPI RegisterMiscControls();
	int WINAPI RegisterStandardControls();
	int WINAPI RegisterXControls();

	int WINAPI StartMessagePump();
	int WINAPI StopMessagePump();


	ATOM WINAPI StrToID(UCString resId);


	int WINAPI UnicodeToMultiByte(UCString lpWideCharStr, int cchWideChar, int unk);
	int WINAPI MultiByteToUnicode(LPCSTR lpMultiByteStr, int cbMultiByte, int unk);

	BOOL WINAPI IsAnimationsEnabled();
	int WINAPI IsPalette(HWND hWnd);
	BOOL WINAPI IsUIAutomationProviderEnabled();

	int WINAPI DUIDrawShadowText(HDC hdcDest, UCString lpchText, int cchText, LPRECT hdcSrc, UINT format, COLORREF color);
}