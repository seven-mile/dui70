#pragma once

namespace DirectUI
{
	class UILIB_API HWNDHost : public ElementWithHWND
	{
	public:
		HWNDHost(const HWNDHost &);
		HWNDHost();
		HWNDHost& operator=(const HWNDHost &);
		
		virtual ~HWNDHost();

		long Initialize(unsigned int, unsigned int, Element*, unsigned long*);
		void Detach();
		unsigned short GetBackgroundOwnerID();
		HWND GetHWNDParent();
		bool GetOptimizeMove();
		bool GetTransparent();
		long GetClientAccessibleImpl(IAccessible**);
		long SetBackgroundOwnerID(UCString);
		long SetOptimizeMove(bool);
		long SetTransparent(bool);

		static long Create(unsigned int, unsigned int, Element*, unsigned long*, Element**pOut);
		static long Create(Element*, unsigned long*, Element**pOut);
		static const PropertyInfo* BackgroundOwnerIDProp();
		static IClassInfo* GetClassInfoPtr();
		static const PropertyInfo* OptimizeMoveProp();
		static long Register();
		static void SetClassInfoPtr(IClassInfo*);
		static const PropertyInfo* ThemeChangedProp();
		static const PropertyInfo* TransparentProp();

		//父类重载
		virtual IClassInfo* GetClassInfoW();
		virtual long GetAccessibleImpl(IAccessible**);
		virtual bool GetKeyFocused();
		virtual unsigned int MessageCallback(LPGMSG);
		virtual void OnDestroy();
		virtual void OnEvent(Event*);
		virtual void OnInput(InputEvent*);
		virtual void OnPropertyChanged(const PropertyInfo*, int, Value*, Value*);

		virtual void Paint(HDC, LPCRECT, LPCRECT, LPRECT, LPRECT);
		virtual void SetKeyFocus();
		virtual void SetWindowDirection(HWND);
		//

		//1
		virtual HWND GetHWND();
		//2
		virtual bool OnMessage(UINT uMsg, WPARAM wParam, LPARAM lParam, LRESULT*);
		//3
		virtual bool OnNotify(UINT uMsg, WPARAM wParam, LPARAM lParam, LRESULT*);
		//4
		virtual bool OnSysChar(UChar);
		//5
		virtual bool OnSinkThemeChanged(UINT uMsg, WPARAM wParam, LPARAM lParam, LRESULT*);
		//6
		virtual bool OnCtrlThemeChanged(UINT, WPARAM wParam, LPARAM lParam, LRESULT*);
		//7
		virtual void OnWindowStyleChanged(WPARAM, const STYLESTRUCT *);
		//8
		virtual int OnAdjustWindowSize(int, int, unsigned int);

	protected:
		static void AttachCtrlSubclassProc(HWND);
		static __int64 CtrlSubclassProc(HWND, unsigned int, unsigned __int64, __int64);

		void PrintRTLControl(HDC, HDC, const RECT&);
		long SetThemeChanged(int);
		void SyncBackground();
		void SyncDirection();
		void SyncFont();
		void SyncForeground();
		void SyncParent();
		void SyncRect(unsigned int, bool);
		void SyncStyle();
		void SyncText();
		void SyncVisible();
		int VerifyParentage();
		HWND CreateAccNameLabel(HWND);
		Element* GetBackgroundOwner();
		HFONT GetFont();
		bool GetStaticColor(HDC, HBRUSH*);
		int GetThemeChanged();
		bool IsMoveDeferred();
		//父类重载
		virtual void OnHosted(Element*);
		virtual void OnUnHosted(Element*);
		//

		//9
		virtual HWND CreateHWND(HWND);
		//10
		virtual bool EraseBkgnd(HDC, LRESULT*);

	private:
		static unsigned int const *g_rgMouseMap[3];
		static IClassInfo* s_pClassInfo;
		static int __stdcall _CtrlWndProc(void *, HWND, unsigned int, unsigned int, long, long *);
		static int WINAPI _SinkWndProc(void *, HWND, unsigned int, unsigned int, long, long *);

		void ApplySinkRegion(RECT const *, bool);
		long GetAccessibleImpl(IAccessible**, bool);
		void GetSinkRect(const LPRECT, LPRECT);
		bool HaveWin32Focus();
		void SyncColorsAndFonts();
		void UnvirtualizePosition();
		void _DeleteCtrlWnd();
	};
}