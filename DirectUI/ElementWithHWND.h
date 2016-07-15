#pragma once
#include "types.h"

namespace DirectUI
{
	class UILIB_API ElementWithHWND : public Element
	{
	public:
		ElementWithHWND(const ElementWithHWND &);
		ElementWithHWND();
		virtual ~ElementWithHWND();
		ElementWithHWND& operator=(const ElementWithHWND &);

		static long Create(Element *, unsigned long *, Element **);
		static IClassInfo * GetClassInfoPtr();
		virtual IClassInfo * GetClassInfoW();
		static long Register();
		static void SetClassInfoPtr(IClassInfo *);

	private:
		static IClassInfo *s_pClassInfo;
	};
}