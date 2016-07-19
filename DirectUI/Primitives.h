#pragma once

namespace DirectUI
{
	
	struct Fill
	{

	};

	struct Cursor
	{

	};

	struct Graphic
	{

	};


	struct EnumMap
	{

	};

	struct UiaRect
	{

	};

	struct PropertyInfo
	{

	};

	struct DepRecs
	{

	};

	class UILIB_API NavReference
	{
	public:
		void Init(Element *, RECT *);
		NavReference& operator=(NavReference const &);
	};
}