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

	struct PropertyInfo
	{

	};

	struct DepRecs
	{

	};

	struct UILIB_API NavReference
	{
	public:
		NavReference() = delete;
		NavReference(const NavReference&) = delete;
		~NavReference() = delete;

		void Init(Element *, RECT *);
		NavReference& operator=(NavReference const &);
	};
}