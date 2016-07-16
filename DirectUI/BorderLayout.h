#pragma once

namespace DirectUI
{
	class UILIB_API BorderLayout :public Layout
	{
	public:
		BorderLayout(const BorderLayout &);
		BorderLayout(void);
		virtual ~BorderLayout(void);
		BorderLayout & operator=(const BorderLayout &);

		static long __stdcall Create(int, int *,Value * *);
		static long __stdcall Create(Layout * *);

		virtual void  DoLayout(Element *, int, int);
		virtual Element * GetAdjacent(Element *, Element *, int, const NavReference *, unsigned long);
		void Initialize(void);
		virtual void OnAdd(Element *, Element * *, unsigned int);
		virtual void OnLayoutPosChanged(Element *, Element *, int, int);
		virtual void OnRemove(Element *, Element * *, unsigned int);
		virtual SIZE UpdateDesiredSize(Element *, int, int, Surface *);

	private:
		void SetClient(Element *);
	};
}