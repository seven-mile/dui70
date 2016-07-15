#pragma once
#include "types.h"

namespace DirectUI
{
	class Value
	{
	public:
		Value& operator=(const Value &);
		void AddRef();

		static Value* CreateAtom(unsigned short);
		static Value* CreateAtom(const String);
		static Value* CreateBool(bool);
		static Value* CreateColor(unsigned long);
		static Value* CreateColor(unsigned long, unsigned long, unsigned char);
		static Value* CreateColor(unsigned long, unsigned long, unsigned long, unsigned char);
		static Value* CreateCursor(HICON);
		static Value* CreateCursor(const String);
		static Value* CreateDFCFill(unsigned int, unsigned int);
		static Value* CreateDTBFill(const String, int, int);
		static Value* CreateElementList(DynamicArray<class Element *, 0> *);
		static Value* CreateElementRef(class Element *);
		static Value* CreateEncodedString(const String);
		static Value* CreateExpression(Expression *);
		static Value* CreateFill(const class Fill &);
		static Value* CreateGraphic(HBITMAP, unsigned char, unsigned int, bool, bool, bool);
		static Value* CreateGraphic(HENHMETAFILE, HENHMETAFILE);
		static Value* CreateGraphic(HICON, bool, bool, bool);
		static Value* CreateGraphic(const String, unsigned char, unsigned int, unsigned short, unsigned short, HINSTANCE, bool, bool);
		static Value* CreateGraphic(const String, unsigned short, unsigned short, HINSTANCE, bool, bool);
		static Value* CreateInt(int);
		static Value* CreateLayout(class Layout *);
		static Value* CreatePoint(int, int);
		static Value* CreateRect(int, int, int, int);
		static Value* CreateSize(int, int);
		static Value* CreateString(const String, HINSTANCE);
		static Value* CreateStyleSheet(StyleSheet *);

		bool GetBool();
		class Cursor * GetCursor();
		class Element * GetElement();
		DynamicArray<class Element *, 0>* GetElementList();
		class Expression * GetExpression();
		const class Fill * GetFill();
		class Graphic * GetGraphic();
		void * GetImage();
		int GetInt();
		class Layout* GetLayout();
		const LPPOINT GetPoint();
		const LPRECT GetRect();
		int GetRefCount() const;
		const LPSIZE GetSize();
		unsigned short const * GetString();
		StyleSheet * GetStyleSheet();
		int GetType() const;

		unsigned short GetAtom();
		static Value* GetAtomZero();
		static Value* GetBoolFalse();
		static Value* GetBoolTrue();
		static Value* GetColorTrans();
		static Value* GetCursorNull();
		static Value* GetElListNull();
		static Value* GetElementNull();
		static Value* GetExprNull();
		static Value* GetIntZero();
		static Value* GetLayoutNull();
		static Value* GetNull();
		static Value* GetPointZero();
		static Value* GetRectZero();
		static Value* GetSheetNull();
		static Value* GetSizeZero();
		static Value* GetStringNull();
		static Value* GetUnavailable();
		static Value* GetUnset();

		bool IsEqual(Value *);
		void Release();
		String ToString(String, unsigned int) const;
	private:
		void _ZeroRelease();
		static long StrDupW(const String, String*);
	};
}