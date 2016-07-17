#pragma once

namespace DirectUI
{
	class UILIB_API LinkedList
	{
	public:
		LinkedList(void);
		~LinkedList(void);
		LinkedList & operator=(LinkedList const &);
		void Add(class LinkedListNode *);
		void Remove(class LinkedListNode *);
		class LinkedListNode * RemoveTail(void);
	};
}