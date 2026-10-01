#include <Windows.h>

#include <Vsstyle.h>
#include <vssym32.h>

#include <wil/common.h>
#include <wil/result.h>

#include <filesystem>
#include <format>
#include <fstream>
#include <functional>
#include <sstream>

#include <DirectUI.h>  // generated aggregate (tools/dui-pipeline/emit_headers.py)

#include <detours/detours.h>

#pragma comment(lib, "dui70.lib")
#pragma comment(lib, "comctl32.lib")
#include "resource.h"

using namespace DirectUI;

// extern-C re-declarations so the animation gate probe does not depend on the
// generated aggregate header (which a concurrent pipeline run rewrites).
extern "C" {
BOOL WINAPI IsAnimationsEnabled(void);
void WINAPI EnableAnimations(void);
void WINAPI DisableAnimations(void);
}

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

void DumpClassInfo(IClassInfo *info) {

  // Output dir override; defaults to a "class-dump" folder next to the exe.
  wchar_t dumpDir[MAX_PATH];
  GetModuleFileNameW(nullptr, dumpDir, MAX_PATH);
  auto dumpPath = std::filesystem::path{dumpDir}.parent_path() / L"class-dump";
  std::filesystem::create_directories(dumpPath);

  std::wstring name = (LPCWSTR)info->GetName();

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

// ---------------------------------------------------------------------------
// DUser usage probe: hook DUser.dll exports that dui70 delay-loads and count
// invocations, proving at runtime which DUser primitives DirectUI's
// render/hit-test/event path actually goes through.
// ---------------------------------------------------------------------------

#include <atomic>

struct DUserCallCount {
  const char *name;
  std::atomic<uint64_t> count{0};
};

static DUserCallCount g_duserCounts[16];
static std::atomic<bool> g_duserProbeReady{false};

static void LogDUserCall(int slotIdx) {
  auto &c = g_duserCounts[slotIdx];
  uint64_t n = ++c.count;
  if (n <= 3) {
    char buf[128];
    sprintf_s(buf, "[duser-probe] %s call #%llu\n", c.name,
              (unsigned long long)n);
    OutputDebugStringA(buf);
  }
}

// Pure-assembly counting stubs: each stub does
//   lea rax, [counter]      ; 48 8D 05 rel32
//   lock inc qword [rax]    ; F0 48 FF 00
//   mov rax, realFn         ; 48 B8 imm64
//   jmp rax                 ; FF E0
// rax is volatile, so this forwards ALL other registers, the whole stack
// frame and xmm args verbatim — ABI-safe for any parameter count (unlike
// C probe functions, which broke CreateGadget during dui70 startup).
#include <cstdint>

static unsigned char *AllocStub(const void *counterAddr, const void *realFn) {
  static unsigned char *pool = nullptr;
  static size_t used = 0;
  const size_t kStubSize = 32;
  if (!pool || used + kStubSize > 4096) {
    pool = (unsigned char *)VirtualAlloc(nullptr, 4096, MEM_COMMIT | MEM_RESERVE,
                                         PAGE_READWRITE);
    used = 0;
  }
  unsigned char *stub = pool + used;
  used += kStubSize;
  // mov rax, imm64 -> counter   (48 B8 imm64)
  stub[0] = 0x48; stub[1] = 0xB8;
  memcpy(stub + 2, &counterAddr, 8);
  // lock inc qword ptr [rax]    (F0 48 FF 00)
  stub[10] = 0xF0; stub[11] = 0x48; stub[12] = 0xFF; stub[13] = 0x00;
  // mov rax, imm64 -> realFn    (48 B8 imm64)
  stub[14] = 0x48; stub[15] = 0xB8;
  memcpy(stub + 16, &realFn, 8);
  // jmp rax                     (FF E0)
  stub[24] = 0xFF; stub[25] = 0xE0;
  // pad
  for (int i = 26; i < 32; i++) stub[i] = 0xCC;
  return stub;
}

static void MakeStubExecutable(unsigned char *pool) {
  DWORD oldProt = 0;
  VirtualProtect(pool, 4096, PAGE_EXECUTE_READ, &oldProt);
  // note: all stubs share one 4K pool; flush once after emitting all
}

static unsigned char *g_stubPoolBase = nullptr;
// =========================================================================
// Animation experiment helpers (reconstructed; parent-agent experiment)
// =========================================================================
enum DirectUIAnimation {
  Anim_None = 0x0,
  Anim_Linear = 0x1,
  Anim_Log = 0x2,
  Anim_Exp = 0x3,
  Anim_S = 0x4,
  Anim_DelayShort = 0x10,
  Anim_DelayMedium = 0x20,
  Anim_DelayLong = 0x30,
  Anim_Alpha = 0x100,
  Anim_Position = 0x1000,
  Anim_Size = 0x2000,
  Anim_SizeH = 0x3000,
  Anim_SizeV = 0x4000,
  Anim_Rectangle = 0x5000,
  Anim_RectangleH = 0x6000,
  Anim_RectangleV = 0x7000,
  Anim_Scale = 0x10000,
  Anim_Reverse = 0x1000000,
  Anim_VeryFast = 0x10000000,
  Anim_Fast = 0x20000000,
  Anim_MediumFast = 0x30000000,
  Anim_Medium = 0x40000000,
  Anim_MediumSlow = 0x50000000,
  Anim_Slow = 0x60000000,
  Anim_VerySlow = 0x70000000,
};

static std::wstring g_animLogText;
static std::wstring g_animLogDir;

static void AnimLog(const std::wstring &line) {
  g_animLogText += line + L"\n";
  OutputDebugString(line.c_str());
  OutputDebugString(L"\n");
  if (!g_animLogDir.empty()) {
    auto path = std::filesystem::path{g_animLogDir} / L"anim-experiment.log";
    HANDLE h = CreateFileW(path.c_str(), FILE_APPEND_DATA, FILE_SHARE_READ,
                           nullptr, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL,
                           nullptr);
    if (h != INVALID_HANDLE_VALUE) {
      // UTF-16 BOM for a fresh file
      if (GetFileSize(h, nullptr) == 0) {
        DWORD w2 = 0;
        WriteFile(h, "\xFF\xFE", 2, &w2, nullptr);
      }
      DWORD written = 0;
      WriteFile(h, line.c_str(), (DWORD)(line.size() * sizeof(wchar_t)),
                &written, nullptr);
      WriteFile(h, L"\r\n", 2, &written, nullptr);
      CloseHandle(h);
    }
  }
}

static void AnimLogFlush(const std::wstring &dir) {
  if (g_animLogText.empty())
    return;
  std::wstring d = dir.empty() ? g_animLogDir : dir;
  if (d.empty())
    return;
  auto path = std::filesystem::path{d} / L"anim-experiment.log";
  HANDLE h = CreateFileW(path.c_str(), FILE_APPEND_DATA, FILE_SHARE_READ,
                         nullptr, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
  if (h != INVALID_HANDLE_VALUE) {
    DWORD written = 0;
    WriteFile(h, g_animLogText.c_str(),
              (DWORD)(g_animLogText.size() * sizeof(wchar_t)), &written,
              nullptr);
    CloseHandle(h);
  }
}

static Element *g_animTarget = nullptr;   // hover-fade target (Accept button)
static Element *g_animTarget2 = nullptr;  // size-anim target (Reject button)

static ULONGLONG g_animT0 = 0;

static void LogTargetState(const wchar_t *tag) {
  if (!g_animTarget)
    return;
  AnimLog(std::format(
      L"[{:8.1f}ms] {} alpha={} anim=0x{:X} hasAnim={} pvl=0x{:X} sz={}x{}",
      (double)(GetTickCount64() - g_animT0), tag, g_animTarget->GetAlpha(),
      (unsigned)g_animTarget->GetAnimation(), g_animTarget->HasAnimation(),
      (unsigned)g_animTarget->GetPVLAnimationState(),
      g_animTarget->GetWidth(), g_animTarget->GetHeight()));
}
static void DumpDUserCounts(const wchar_t *tag) {
  wchar_t path[MAX_PATH];
  GetModuleFileNameW(nullptr, path, MAX_PATH);
  auto out = std::filesystem::path{path}.parent_path() /
             L"duser-call-counts.txt";
  std::wostringstream os;
  os << L"=== DUser probe: " << tag << L" ===\n";
  os << L"probe ready: " << (g_duserProbeReady.load() ? L"yes" : L"NO")
     << L"\n";
  wchar_t wname[64];
  for (auto &c : g_duserCounts) {
    if (!c.name)
      continue;
    int i = 0;
    for (; c.name[i] && i < 63; i++)
      wname[i] = (wchar_t)c.name[i];
    wname[i] = 0;
    os << std::format(L"  {:<28} {}\n", wname, c.count.load());
  }
  std::wstring text = os.str();
  OutputDebugString(text.c_str());

  // Robust append via Win32 (wofstream failed to materialize in practice).
  HANDLE h = CreateFileW(out.c_str(), FILE_APPEND_DATA, FILE_SHARE_READ,
                         nullptr, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
  if (h != INVALID_HANDLE_VALUE) {
    DWORD written = 0;
    WriteFile(h, text.c_str(), (DWORD)(text.size() * sizeof(wchar_t)),
              &written, nullptr);
    // UTF-16 BOM if file was just created
    if (GetFileSize(h, nullptr) == written) {
      SetFilePointer(h, 0, nullptr, FILE_BEGIN);
      WriteFile(h, "\xFF\xFE", 2, &written, nullptr);
    }
    CloseHandle(h);
  }
}

// Patch dui70's DELAY-IMPORT IAT slots with counting stubs. Only dui70's own
// delay-import calls are intercepted; DUser-internal calls are untouched.
// Slot layout: dui70+0x195018 + 8*i (70-entry table, dumpbin order).
static const char *kSlotNames[16] = {
    "InitGadgets",          "CreateGadget",       "DeleteHandle",
    "SetGadgetStyle",       "SetGadgetMessageFilter", "DUserSendEvent",
    "DUserPostEvent",       "InvalidateGadget",   "FindGadgetFromPoint",
    "GetGadgetRect",        "SetGadgetRect",      "GetGadgetVisual",
    "AttachWndProcW",       "ForwardGadgetMessage", "BuildAnimation",
    "MapGadgetPoints"};
static const int kSlotIndex[16] = {69, 12, 11, 6, 13, 14, 15, 26, 10,
                                   5,  2,  56, 65, 64, 19, 9};

inline void HookDUserExports() {
  HMODULE du = GetModuleHandleW(L"DUser.dll");
  if (!du) {
    OutputDebugStringA(
        "[duser-probe] DUser.dll not loaded at hook time; loading\n");
    du = LoadLibraryW(L"DUser.dll");
    if (!du) {
      OutputDebugStringA("[duser-probe] failed to load DUser.dll\n");
      return;
    }
  }
  HMODULE dui = GetModuleHandleW(L"dui70.dll");
  if (!dui) {
    OutputDebugStringA("[duser-probe] dui70.dll not loaded\n");
    return;
  }

  DWORD hookMask = 0xFFFF;
  wchar_t maskBuf[16];
  if (GetEnvironmentVariableW(L"DUSER_HOOK_MASK", maskBuf, 16) > 0)
    hookMask = (DWORD)wcstoul(maskBuf, nullptr, 16);

  UINT64 iatBase = (UINT64)dui + 0x195018;
  unsigned char *firstStub = nullptr;
  for (int i = 0; i < 16; i++) {
    g_duserCounts[i].name = kSlotNames[i];
    if (!((hookMask >> i) & 1))
      continue;
    FARPROC p = GetProcAddress(du, kSlotNames[i]);
    if (!p)
      continue;
    unsigned char *stub =
        AllocStub((const void *)&g_duserCounts[i].count, (const void *)p);
    if (!firstStub)
      firstStub = stub;
    UINT64 slotVA = iatBase + 8 * (UINT64)kSlotIndex[i];
    DWORD oldProt = 0;
    if (VirtualProtect((PVOID)slotVA, 8, PAGE_READWRITE, &oldProt)) {
      *(UINT64 *)slotVA = (UINT64)stub;
      VirtualProtect((PVOID)slotVA, 8, oldProt, &oldProt);
    }
  }
  // Make the stub pool executable (all stubs share one page).
  if (firstStub) {
    // round down to page
    UINT64 page = (UINT64)firstStub & ~0xFFFULL;
    DWORD oldProt = 0;
    VirtualProtect((PVOID)page, 0x1000, PAGE_EXECUTE_READ, &oldProt);
    FlushInstructionCache(GetCurrentProcess(), (PVOID)page, 0x1000);
  }
  g_duserProbeReady = true;
  OutputDebugStringA("[duser-probe] IAT slots patched with asm stubs\n");
  DumpDUserCounts(L"sanity: right after hook install");
}
int CALLBACK WinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance,
                     LPSTR lpCmdLine, int nCmdShow) {

  THROW_IF_FAILED(CoInitializeEx(NULL, 0));

  // Install DUser probe BEFORE InitProcessPriv/InitThread so that even the
  // initialization-time DUser calls (InitGadgets etc.) are counted.
  // DISABLED for the animation experiment: detouring DUser exports caused a
  // crash in Element::_DisplayNodeCallback (dui70+0x2EDD2) once DUser starts
  // driving transition callbacks.
  HookDUserExports(); // IAT-slot patch (no detours)

  THROW_IF_FAILED(InitProcessPriv(14, NULL, 0, true));
  THROW_IF_FAILED(InitThread(2));

  // uncomment to update class definitions
  // HookClassFactoryRegister();
  THROW_IF_NTSTATUS_FAILED(RegisterAllControls());
  DumpDUserCounts(L"after RegisterAllControls");

  NativeHWNDHost *pwnd;

  NativeHWNDHost::Create(
      (UCString)L"Microsoft DirectUI Test", NULL, NULL,
      // CW_USEDEFAULT, CW_USEDEFAULT, CW_USEDEFAULT, CW_USEDEFAULT,
      600, 400, 800, 600, WS_EX_WINDOWEDGE, WS_OVERLAPPEDWINDOW | WS_VISIBLE, 0,
      &pwnd);
  DumpDUserCounts(L"after NativeHWNDHost::Create");

  DUIXmlParser *pParser;

  THROW_IF_FAILED(DUIXmlParser::Create(&pParser, NULL, NULL, NULL, NULL));
  DumpDUserCounts(L"after DUIXmlParser::Create");

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
  DumpDUserCounts(L"after SetXMLFromResource");

  unsigned long defer_key;
  HWNDElement *hwnd_element;

  HWNDElement::Create(pwnd->GetHWND(), true, 0, NULL, &defer_key,
                      (Element **)&hwnd_element);
  DumpDUserCounts(L"after HWNDElement::Create");

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

  LogListener lis;
  hr = pWizardMain->AddListener(&lis);
  THROW_IF_FAILED(hr);

  int btn_count = 0;

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

  // =========================================================================
  // EXPERIMENT: animated Alpha (Accept) + animated Rectangle (Reject)
  // =========================================================================
  g_animT0 = GetTickCount64();
  {
    wchar_t exeDir[MAX_PATH];
    GetModuleFileNameW(nullptr, exeDir, MAX_PATH);
    *wcsrchr(exeDir, L'\\') = 0;
    g_animLogDir = exeDir;
  }
  g_animTarget = accept_btn;
  g_animTarget2 = reject_btn;

  AnimLog(L"=== DirectUI animation experiment ===");
  LogTargetState(L"init");
  {
    AnimLog(std::format(L"IsAnimationsEnabled() = {} (before EnableAnimations)",
                        IsAnimationsEnabled() ? L"true" : L"false"));
    if (!IsAnimationsEnabled()) {
      EnableAnimations();
      AnimLog(std::format(L"IsAnimationsEnabled() = {} (after EnableAnimations)",
                          IsAnimationsEnabled() ? L"true" : L"false"));
    }
  }

  // --- probe 1: SetAnimation(S|Fast|Alpha) now; SetAlpha deferred to timer
  //     tick #2 so screenshots can catch the visual interpolation in flight ---
  {
    HRESULT hrA =
        accept_btn->SetAnimation(Anim_S | Anim_Fast | Anim_Alpha);
    AnimLog(std::format(L"SetAnimation(S|Fast|Alpha=0x{:X}) -> 0x{:08X}",
                        (unsigned)(Anim_S | Anim_Fast | Anim_Alpha),
                        (unsigned)hrA));
    LogTargetState(L"after SetAnimation");
  }

  // --- probe 2: SetAnimation(Log|Medium|Rectangle) + SetWidth(220) ---
  {
    HRESULT hrC = reject_btn->SetAnimation(Anim_Log | Anim_Medium |
                                           Anim_Rectangle);
    AnimLog(std::format(L"SetAnimation(Log|Medium|Rectangle=0x{:X}) -> 0x{:08X}",
                        (unsigned)(Anim_Log | Anim_Medium | Anim_Rectangle),
                        (unsigned)hrC));
    HRESULT hrD = reject_btn->SetWidth(220);
    AnimLog(std::format(L"SetWidth(220) -> 0x{:08X}", (unsigned)hrD));
  }

  // --- hover handler: fade the Accept button in/out on MouseWithin ---
  EventListener anim_listener(
      [](Element *, Event *) {},
      [](Element *elem, const PropertyInfo *prop, Value *, Value *) {
        static const PropertyInfo *mouseWithinPI = Element::MouseWithinProp();
        static const PropertyInfo *alphaPI = Element::AlphaProp();
        if (prop == mouseWithinPI && g_animTarget) {
          bool within = elem->GetMouseWithin();
          if (elem == g_animTarget || g_animTarget->IsDescendent(elem) ||
              elem->IsDescendent(g_animTarget)) {
            AnimLog(std::format(
                L"HOVER {:p} within={} -> SetAlpha({})", (void *)elem, within,
                within ? 96 : 255));
            g_animTarget->SetAlpha(within ? 96 : 255);
          }
        } else if (prop == alphaPI && elem == g_animTarget) {
          // log every Alpha property change: if the framework animates, we
          // expect ONE property change (target) while the VISUAL interpolates
          // in DUser; if not, also just one. The log proves which.
          AnimLog(std::format(L"Alpha prop changed on target: now {}",
                              g_animTarget->GetAlpha()));
        }
      });
  hr = pWizardMain->AddListener(&anim_listener);
  THROW_IF_FAILED(hr);

  // --- poll: sample state via a timer inside the real message loop ---
  {
    HWND host = pwnd->GetHWND();
    static int pollCount = 0;
    SetTimer(host, 0xA71, 50, [](HWND, UINT, UINT_PTR, DWORD) {
      // tick 2 (t=100ms): kick off the animated fade 255 -> 64 (Fast=0.25s)
      if (pollCount == 2) {
        if (g_animTarget) {
          AnimLog(L"timer tick 2: SetAlpha(64) NOW — animation starts");
          g_animTarget->SetAlpha(64);
        }
      }
      // tick 20 (t=1s): animate back up so we can also capture the reverse
      if (pollCount == 20) {
        if (g_animTarget) {
          AnimLog(L"timer tick 20: SetAlpha(255) — reverse animation");
          g_animTarget->SetAlpha(255);
        }
      }
      LogTargetState(L"poll");
      pollCount++;
    });
  }

  DumpDuiTree(pWizardMain, 0);
  DumpDUserCounts(L"after tree build, before message pump");
  StartMessagePump();
  DumpDUserCounts(L"after message pump exited");

  AnimLog(L"=== message pump exited ===");

  UnInitProcessPriv(NULL);
  return 0;
}
