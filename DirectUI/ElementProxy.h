#pragma once

namespace DirectUI
{
	class UILIB_API ElementProxy
	{
	public:
		ElementProxy(ElementProxy const &);
		ElementProxy(void);
		ElementProxy & operator=(ElementProxy const &);

		static ElementProxy * __stdcall Create(Element *);
		//1
		virtual long DoMethod(int, char *);
	protected:
		long GetAutomationId(VARIANT *);
		long GetBoundingRect(struct UiaRect *);
		long GetContent(VARIANT *, IAccessible *);
		void GetControlType(VARIANT *, IAccessible *);
		long GetFragmentRoot(IRawElementProviderFragmentRoot * *);
		long GetHwnd(HWND *);
		long GetLabel(VARIANT *);
		long GetProperty(VARIANT *, int);
		long GetProviderOptions(ProviderOptions *);
		long GetRuntimeId(SAFEARRAY * *);
		long IsPatternSupported(Schema::Pattern, bool *);
		long Navigate(NavigateDirection, IRawElementProviderFragment**);
		long SetString(VARIANT *, UCString (DirectUI::Element::*)(Value * *));
		int _UsesUIAProxies(void);

		//2
		virtual void Init(Element *);

	};
}