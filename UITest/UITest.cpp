// UITest -- a minimal, readable demonstration of using DirectUI through the
// generated aggregate headers.
//
// What it shows, in order:
//   1. IElementListener implemented two ways (a logging listener and a
//      std::function-based one) and attached to an element tree.
//   2. DumpClassInfo, which walks IClassInfo reflection data. That is the same
//      output as docs/duixml-classinfo/; HookClassFactoryRegister() below is how
//      it is regenerated.
//   3. The animation system: SetAnimation() with a combined bit-field, plus a
//      hover-driven alpha fade. See UITest/DuiEnums.h for the bit layout.
//
// Built by tools/dui-pipeline/gen_uitest_proj.ps1 (which does not go through
// UITest.vcxproj) and asserted by tools/dui-pipeline/run.ps1 step 5: the window
// must appear with title "Microsoft DirectUI Test" and dui70.dll must load from
// System32.

#include <Windows.h>

#include <Vsstyle.h>
#include <vssym32.h>

#include <wil/common.h>
#include <wil/result.h>

#include <filesystem>
#include <format>
#include <fstream>
#include <functional>

#include <DirectUI.h>  // generated aggregate (tools/dui-pipeline/emit_headers.py)

#include <detours/detours.h>

#include "DuiEnums.h"

#pragma comment(lib, "dui70.lib")
#pragma comment(lib, "comctl32.lib")
#include "resource.h"

using namespace DirectUI;

// ---------------------------------------------------------------------------
// 1. IElementListener, written out longhand.
//    Every method is a notification; only a couple are interesting here, so the
//    rest just trace to the debugger.
// ---------------------------------------------------------------------------
struct LogListener : public IElementListener {

  // 0
  void OnListenerAttach(Element *elem) override {
    OutputDebugString(std::format(L"attach: {:p}\n", (void *)elem).c_str());
  }
  // 1
  void OnListenerDetach(Element *elem) override {
    OutputDebugString(std::format(L"detach: {:p}\n", (void *)elem).c_str());
  }
  // 2
  bool OnPropertyChanging(Element *elem, const PropertyInfo *prop, int unk,
                          Value *v1, Value *v2) override {
    OutputDebugString(
        std::format(L"prop change: {:p} {} {} {:p}<{}> {:p}<{}>\n",
                    (void *)elem, (PCWSTR)prop->name, unk, (void *)v1,
                    v1->GetType(), (void *)v2, v2->GetType())
            .c_str());
    return true;
  }
  // 3
  void OnListenedPropertyChanged(Element *elem, const PropertyInfo *prop,
                                 int type, Value *v1, Value *v2) override {
    OutputDebugString(
        std::format(L"listened prop change: {:p} {} {} {:p}<{}> {:p}<{}>\n",
                    (void *)elem, (PCWSTR)prop->name, type, (void *)v1,
                    v1->GetType(), (void *)v2, v2->GetType())
            .c_str());
  }
  // 4
  void OnListenedEvent(Element *elem, struct Event *ev) override {
    OutputDebugString(
        std::format(L"listened event: {:p} {:p}\n", (void *)elem, (void *)ev)
            .c_str());
  }
  // 5
  void OnListenedInput(Element *elem, struct InputEvent *iev) override {
    OutputDebugString(
        std::format(L"listened input: {:p} {:p}\n", (void *)elem, (void *)iev)
            .c_str());
  }
};

// The same interface, but driven by std::function so callers can pass lambdas
// and only pay for the callbacks they care about.
struct EventListener : public IElementListener {

  using handler_t = std::function<void(Element *, Event *)>;
  using prop_handler_t =
      std::function<void(Element *, const PropertyInfo *, Value *, Value *)>;

  handler_t f;
  prop_handler_t on_prop;

  EventListener(handler_t f) : f(f) {}
  EventListener(handler_t f, prop_handler_t on_prop)
      : f(f), on_prop(on_prop) {}

  void OnListenerAttach(Element *elem) override {}
  void OnListenerDetach(Element *elem) override {}
  bool OnPropertyChanging(Element *elem, const PropertyInfo *prop, int unk,
                          Value *v1, Value *v2) override {
    return true;
  }
  void OnListenedPropertyChanged(Element *elem, const PropertyInfo *prop,
                                 int type, Value *v1, Value *v2) override {
    if (on_prop)
      on_prop(elem, prop, v1, v2);
  }
  void OnListenedEvent(Element *elem, struct Event *iev) override {
    f(elem, iev);
  }
  void OnListenedInput(Element *elem, struct InputEvent *ev) override {}
};

std::wstring to_string(ValueType type) {
  switch (type) {
  case ValueType::Unavailable:
    return L"Unavailable";
  case ValueType::Unset:
    return L"Unset";
  case ValueType::Null:
    return L"Null";
  case ValueType::Int:
    return L"Int";
  case ValueType::Bool:
    return L"Bool";
  case ValueType::Element:
    return L"Element";
  case ValueType::Ellist:
    return L"Ellist";
  case ValueType::String:
    return L"String";
  case ValueType::Point:
    return L"Point";
  case ValueType::Size:
    return L"Size";
  case ValueType::Rect:
    return L"Rect";
  case ValueType::Color:
    return L"Color";
  case ValueType::Layout:
    return L"Layout";
  case ValueType::Graphic:
    return L"Graphic";
  case ValueType::Sheet:
    return L"Sheet";
  case ValueType::Expr:
    return L"Expr";
  case ValueType::Atom:
    return L"Atom";
  case ValueType::Cursor:
    return L"Cursor";
  case ValueType::Float:
    return L"Float";
  case ValueType::DblList:
    return L"DblList";
  default:
    throw std::logic_error{"unreachable"};
  }
}

// ---------------------------------------------------------------------------
// 2. Reflection: dump one class's name, base class, and property table.
//    With HookClassFactoryRegister() enabled this runs for every control dui70
//    registers, writing class-dump/<Name>Class.g.txt next to the exe.
// ---------------------------------------------------------------------------
void DumpClassInfo(IClassInfo *info) {

  // Output dir override; defaults to a "class-dump" folder next to the exe.
  wchar_t dumpDir[MAX_PATH];
  GetModuleFileNameW(nullptr, dumpDir, MAX_PATH);
  auto dumpPath = std::filesystem::path{dumpDir}.parent_path() / L"class-dump";
  std::filesystem::create_directories(dumpPath);

  std::wstring name = (LPCWSTR)info->GetName();

  // The `.g.txt` suffix is load-bearing: tools/dui-pipeline/verify.py skips files
  // with this suffix in its concurrent-write check, and the archived dumps in
  // docs/duixml-classinfo/ keep the same naming.
  std::wofstream os{dumpPath / (name + L"Class.g.txt")};

  os << (std::format(L"ClassInfo: <{}>\n", name).c_str());

  auto *base = info->GetBaseClass();
  os << (std::format(L"  Base Class: <{}>\n",
                     base ? (LPCWSTR)base->GetName() : L"None")
             .c_str());

  os << (L"  Properties:\n");
  for (int i = 0; i < info->GetPICount(); i++) {
    auto prop = info->EnumPropertyInfo(i);
    os << (std::format(L"    [{}]: {}\n", (LPCWSTR)prop->name,
                       to_string(prop->cap->type))
               .c_str());
    if (prop->enum_value_map) {
      os << (L"      Enum values:\n");
      for (auto *ptr = prop->enum_value_map; ptr->str_value; ptr++) {
        os << (std::format(L"        {} : 0x{:x} ({})\n",
                           (PCWSTR)ptr->str_value, (UINT32)ptr->int_value,
                           ptr->int_value)
                   .c_str());
      }
    }
  }
}

long (*RealClassFactoryRegister)(CClassFactory *, IClassInfo *) = 0;

HRESULT HookedRegister(CClassFactory *self, IClassInfo *info) {
  DumpClassInfo(info);
  return RealClassFactoryRegister(self, info);
}

// Detour CClassFactory::Register so every control's reflection data is dumped
// during RegisterAllControls(). The address is the known offset in this dui70
// build. Enable the call in WinMain to regenerate the class dumps.
inline void HookClassFactoryRegister() {
  RealClassFactoryRegister =
      (decltype(RealClassFactoryRegister))((UINT64)GetModuleHandle(
                                               L"dui70.dll") +
                                           0x37634);

  DetourTransactionBegin();
  DetourUpdateThread(GetCurrentThread());

  auto pfMine = &HookedRegister;
  DetourAttach(&(PVOID &)RealClassFactoryRegister, *(PBYTE *)&pfMine);
  DetourTransactionCommit();
}

int CALLBACK WinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance,
                     LPSTR lpCmdLine, int nCmdShow) {

  THROW_IF_FAILED(CoInitializeEx(NULL, 0));

  THROW_IF_FAILED(InitProcessPriv(14, NULL, 0, true));
  THROW_IF_FAILED(InitThread(2));

  // uncomment to update class definitions (see DumpClassInfo)
  // HookClassFactoryRegister();
  THROW_IF_NTSTATUS_FAILED(RegisterAllControls());

  NativeHWNDHost *pwnd;

  NativeHWNDHost::Create(
      (UCString)L"Microsoft DirectUI Test", NULL, NULL,
      // CW_USEDEFAULT, CW_USEDEFAULT, CW_USEDEFAULT, CW_USEDEFAULT,
      600, 400, 800, 600, WS_EX_WINDOWEDGE, WS_OVERLAPPEDWINDOW | WS_VISIBLE, 0,
      &pwnd);

  DUIXmlParser *pParser;

  THROW_IF_FAILED(DUIXmlParser::Create(&pParser, NULL, NULL, NULL, NULL));

  pParser->SetParseErrorCallback(
      [](UCString err1, UCString err2, int unk, void *ctx) {
        OutputDebugString(
            std::format(L"err: {}; {}; {}\n", (LPCWSTR)err1, (LPCWSTR)err2, unk)
                .c_str());
        DebugBreak();
      },
      NULL);

  auto hr =
      pParser->SetXMLFromResource(IDR_UIFILE1, hInstance, (HINSTANCE)hInstance);

  unsigned long defer_key;
  HWNDElement *hwnd_element;

  HWNDElement::Create(pwnd->GetHWND(), true, 0, NULL, &defer_key,
                      (Element **)&hwnd_element);

  Element *pWizardMain;
  hr = pParser->CreateElement((UCString)L"WizardMain", hwnd_element, NULL, NULL,
                              (Element **)&pWizardMain);

  THROW_IF_FAILED(hr);

  pWizardMain->SetVisible(true);
  pWizardMain->EndDefer(defer_key);
  pwnd->Host(pWizardMain);

  pwnd->ShowWindow(SW_SHOW);

  auto *title_elem = pWizardMain->FindDescendent(StrToID((UCString)L"SXTitle"));

  auto *accept_btn = (Button *)pWizardMain->FindDescendent(
      StrToID((UCString)L"SXWizardDefaultButton"));
  auto *reject_btn = (Button *)pWizardMain->FindDescendent(
      StrToID((UCString)L"SXWizardAlternateButton"));

  auto *edit_box = (Edit *)pWizardMain->FindDescendent(
      StrToID((UCString)L"SXWizardEditBox"));

  auto *prog = pWizardMain->FindDescendent(
      StrToID((UCString)L"SXWizardLoadingProgress"));

  // The longhand listener first: it just traces everything.
  LogListener lis;
  hr = pWizardMain->AddListener(&lis);
  THROW_IF_FAILED(hr);

  int btn_count = 0;

  // Then the lambda-based one, to react to clicks and Enter.
  EventListener click_listener([&](Element *elem, Event *ev) {
    if (ev->flag != GMF_BUBBLED)
      return;
    if (ev->type == TouchButton::Click) {
      btn_count++;
      hr = title_elem->SetContentString(
          (UCString)std::format(L"Clicked {} times", btn_count).c_str());
      THROW_IF_FAILED(hr);
      prog->SetVisible(true);
    }
    if (ev->type == Edit::Enter) {
      prog->SetVisible(false);
      Value *txt;
      edit_box->GetContentString(&txt);
      hr = title_elem->SetContentString(
          (UCString)std::format(L"Entered: {}", (LPCWSTR)txt->GetString())
              .c_str());
      THROW_IF_FAILED(hr);
    }
  });
  hr = pWizardMain->AddListener(&click_listener);
  THROW_IF_FAILED(hr);

  // -------------------------------------------------------------------------
  // 3. Animation system.
  //
  // SetAnimation takes one 32-bit word that ORs together the sub-fields --
  // easing, delay, alpha, target property, scale, reverse, speed. The layout,
  // and the evidence for each value, live in UITest/DuiEnums.h.
  // -------------------------------------------------------------------------
  if (!IsAnimationsEnabled())
    EnableAnimations();

  // Fade the Accept button (Alpha) with an S-curve easing at Fast speed.
  hr = accept_btn->SetAnimation(
      ToInt(DuiAnim::S | DuiAnim::Fast | DuiAnim::Alpha));
  THROW_IF_FAILED(hr);

  // Animate the Reject button's rectangle instead, with logarithmic easing.
  hr = reject_btn->SetAnimation(
      ToInt(DuiAnim::Log | DuiAnim::Medium | DuiAnim::Rectangle));
  THROW_IF_FAILED(hr);

  // A Rectangle animation only becomes visible once the geometry actually
  // changes, so give it something to animate.
  hr = reject_btn->SetWidth(220);
  THROW_IF_FAILED(hr);

  // Hover fade. This only sets the TARGET alpha; interpolating towards it is
  // dui70/DUser's job, which is the point of the demo -- the callback does not
  // animate anything itself.
  EventListener hover_listener(
      [](Element *, Event *) {},
      [&](Element *elem, const PropertyInfo *prop, Value *, Value *) {
        static const PropertyInfo *mouseWithinPI = Element::MouseWithinProp();
        if (prop != mouseWithinPI)
          return;
        if (elem == accept_btn || accept_btn->IsDescendent(elem) ||
            elem->IsDescendent(accept_btn))
          accept_btn->SetAlpha(accept_btn->GetMouseWithin() ? 96 : 255);
      });
  hr = pWizardMain->AddListener(&hover_listener);
  THROW_IF_FAILED(hr);

  DumpDuiTree(pWizardMain, 0);
  StartMessagePump();

  UnInitProcessPriv(NULL);
  return 0;
}
