#pragma once

namespace DirectUI
{
	class UILIB_API NavScoring
	{
	public:
		void Init(Element *, int, NavReference const *);
		NavScoring & operator=(NavScoring const &);
		int TrackScore(Element *, Element *);
		int Try(Element *, int, NavReference const *, unsigned long);
	};
}