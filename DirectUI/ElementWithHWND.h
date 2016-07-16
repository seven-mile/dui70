#pragma once

namespace DirectUI
{
	class UILIB_API ElementWithHWND : public Element
	{
	public:
		ElementWithHWND(const ElementWithHWND &);
		ElementWithHWND();
		ElementWithHWND& operator=(const ElementWithHWND &);

		virtual ~ElementWithHWND();

		static long Create(Element*, unsigned long*, Element**);
		static IClassInfo* GetClassInfoPtr();
		static long Register();
		static void SetClassInfoPtr(IClassInfo*);

		virtual IClassInfo* GetClassInfoW();

	private:
		static IClassInfo*s_pClassInfo;
	};
}