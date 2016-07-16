#pragma once

namespace DirectUI
{
	class UILIB_API Layout
	{
	public:
		Layout(const Layout &);
		Layout();
		Layout & operator=(const Layout &);

		static HRESULT WINAPI Create(Layout**);
		static void WINAPI UpdateLayoutRect(Element*, int, int, Element*, int, int, int, int);

		void Destroy();
		Element* GetChildFromLayoutIndex(Element*, int, DynamicArray<Element*, 0>*);
		unsigned int GetLayoutChildCount(Element*);
		int GetLayoutIndexFromChild(Element*, Element*);
		void Initialize();
		//0
		virtual void DoLayout(Element*, int, int);

		//1
		virtual SIZE UpdateDesiredSize(Element*, int, int, Surface*);
		//2
		virtual void OnAdd(Element*, Element**, unsigned int);
		//3
		virtual void OnRemove(Element*, Element**, unsigned int);
		//4
		virtual void OnLayoutPosChanged(Element*, Element*, int, int);

		//5
		virtual void Attach(Element*);
		//6
		virtual void Detach(Element*);
		//7
		virtual Element* GetAdjacent(Element*, Element*, int, NavReference const*, unsigned long);
		//8
		virtual ~Layout();
	protected:
		void ClearCacheDirty();
		bool IsCacheDirty();
		void SetCacheDirty();
	};

	class FillLayout : public Layout
	{
	public:
		FillLayout(FillLayout const &);
		FillLayout();
		virtual ~FillLayout();

		FillLayout & operator=(FillLayout const &);

		static HRESULT WINAPI Create(int, int*, Value**);
		static HRESULT WINAPI Create(Layout**);
		virtual void DoLayout(Element*, int, int);
		virtual Element* GetAdjacent(Element*, Element*, int, NavReference const*, unsigned long);
		void Initialize();
		virtual SIZE UpdateDesiredSize(Element*, int, int, Surface*);
	};

    class BorderLayout;
	class GridLayout;
	class FillLayout;
	class FlowLayout;
	class RowLayout;
	class NineGridLayout;
	class ShellBorderLayout;
	class TableLayout;


	class VerticalFlowLayout : public Layout
	{
	public:	
		enum Align
		{
			LAYOUT_LEFT = 0,
			LAYOUT_RIGHT = 1,
			LAYOUT_CENTER = 2,
			LAYOUT_TOP = 0,
			LAYOUT_BOTTOM = 1,
			LAYOUT_MIDDLE = 2
		};

		VerticalFlowLayout(VerticalFlowLayout const &);
		VerticalFlowLayout();
		virtual ~VerticalFlowLayout();
		VerticalFlowLayout & operator=(VerticalFlowLayout const &);

		static HRESULT WINAPI Create(int, int*, Value**);
		static HRESULT WINAPI Create(bool, unsigned int horAlign, unsigned int, unsigned int vertAlign, Layout**);
		virtual void DoLayout(Element*, int, int);
		virtual Element* GetAdjacent(Element*, Element*, int, NavReference const*, unsigned long);
		int GetLine(Element*, Element*);
		void Initialize(bool, unsigned int, unsigned int, unsigned int);
		virtual SIZE UpdateDesiredSize(Element*, int, int, Surface*);

	protected:
		SIZE BuildCacheInfo(Element*, int, int, Surface*,bool);
		static SIZE WINAPI SizeZero(void);
	};
}