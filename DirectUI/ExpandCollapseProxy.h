#pragma once

namespace DirectUI
{
	class UILIB_API ExpandCollapseProxy
	{
	public:
		ExpandCollapseProxy(ExpandCollapseProxy const &);
		ExpandCollapseProxy(void);
		ExpandCollapseProxy & operator=(ExpandCollapseProxy const &);

		static ExpandCollapseProxy * __stdcall Create(Element *);
		//1
		virtual long DoMethod(int, char *);
	protected:
		static bool __stdcall IsPatternSupported(Element *);
		//2
		virtual void Init(Element *);
	};
}