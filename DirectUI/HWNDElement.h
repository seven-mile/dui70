#pragma once
#include "types.h"

namespace DirectUI
{
	class UILIB_API HWNDElement : public ElementWithHWND
	{
	public:
		HWNDElement(const HWNDElement &);
		HWNDElement();
		virtual ~HWNDElement();
		HWNDElement& operator=(const HWNDElement &);

		//0
		virtual void OnPropertyChanged(const PropertyInfo*, int, Value*, Value*);
		//1
		virtual void OnGroupChanged(int, bool);
		//2
		virtual void OnInput(InputEvent*);
		//3
		virtual void OnDestroy();
		//4
		virtual void OnEvent(Event*);
		//5
		virtual void UpdateTooltip(Element*);

		//6
		virtual void ActivateTooltip(Element*, unsigned long);
		//7
		virtual void RemoveTooltip(Element*);

		//8
		virtual IClassInfo* GetClassInfoW();
		//9
		virtual long GetAccessibleImpl(IAccessible**);


		//HWNDElement ÐÂÔöº¯Êý
		//10
		virtual HWND GetHWND();

		//11
		virtual void OnThemeChanged(class ThemeChangedEvent*);

		//12
		virtual void OnNoChildWithShortcutFound(class KeyboardEvent*);

		//13
		virtual void OnGetDlgCode(LPMSG, LRESULT*);
		//14
		virtual void OnWmThemeChanged(WPARAM wParam, LPARAM lParam);
		//15
		virtual void OnCompositionChanged();

		//16
		virtual bool CanSetFocus();

		static class UID CompositionChange();
		static HRESULT WINAPI Create(HWND, bool, unsigned int, Element*, unsigned long*, Element**pOut);
		//17
		virtual long CreateStyleParser(DUIXmlParser**);
		void DelayActivateTooltip();
		Element* ElementFromPoint(LPPOINT);
		static bool FindShortcut(unsigned short, Element*, Element**, int*, int*, int);
		void FlushWorkingSet();
		static IClassInfo* GetClassInfoPtr();

		static HWNDElement* GetFocusedHWNDElement();

		static Element* GetKeyFocusedElement();
		unsigned short GetUIState();
		bool GetWrapKeyboardNavigate();
		long Initialize(HWND, bool, unsigned int, Element*, unsigned long*);
		bool IsFirstElement(Element*);
		bool IsLastElement(Element*);


		static long Register();
		static void SetClassInfoPtr(IClassInfo*);

		void SetFocus(bool);
		void SetParentSizeControl(bool);
		void SetScreenCenter(bool);
		long SetWrapKeyboardNavigate(bool);
		bool ShowAccel(void);
		bool ShowFocus(void);
		void ShowUIState(bool, bool);
		static class UID ThemeChange();

		void ToggleUIState(bool, bool);
		static const PropertyInfo* WINAPI WrapKeyboardNavigateProp();

		static __int64 StaticWndProc(HWND, UINT uMsg, WPARAM wParam, LPARAM lParam);
		//18
		virtual LRESULT WndProc(HWND, UINT uMsg, WPARAM wParam, LPARAM lParam);

	protected:
		static bool FindShortcutRecursive(unsigned short, Element*, Element**, int*, int*, int);

	private:
		static IClassInfo* s_pClassInfo;
	};
}