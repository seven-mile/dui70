#pragma once

namespace DirectUI
{
	class FontCheckOut
	{
	public:
		FontCheckOut(Element *, HDC);
		~FontCheckOut(void);
		FontCheckOut & operator=(FontCheckOut const &);
	};
}