#include "DirectUI.h"

namespace DirectUI
{
	RefcountBase::RefcountBase()
	{
	}

	RefcountBase:: ~RefcountBase()
	{

	}

	long RefcountBase::AddRef()
	{
		return 0;
	}
	long RefcountBase::Release()
	{
		return 0;
	}
}