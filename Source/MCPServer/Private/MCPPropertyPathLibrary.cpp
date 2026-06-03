// Copyright Epic Games, Inc. All Rights Reserved.

#include "MCPPropertyPathLibrary.h"

#include "MCPServer.h"
#include "DetailRowMenuContext.h"
#include "PropertyEditorModule.h"
#include "PropertyHandle.h"

#include "Framework/MetaData/DriverIdMetaData.h"
#include "HAL/PlatformApplicationMisc.h"
#include "Styling/CoreStyle.h"
#include "ToolMenus.h"
#include "Types/ISlateMetaData.h"

#define LOCTEXT_NAMESPACE "MCPPropertyPath"

namespace MCPPropertyPath
{
    static const FName DynamicSectionName = TEXT("MCPServer_PropertyPath_DynamicSection");
    static const FName EntryName          = TEXT("MCPServer_CopyPropertyPath");
}

// ── UMCPPropertyPathLibrary ───────────────────────────────────────────────────

FString UMCPPropertyPathLibrary::BuildPropertyPath(UObject* Object, const FString& PropPath)
{
    const FString ObjPath = IsValid(Object) ? Object->GetPathName() : FString();

    if (ObjPath.IsEmpty() && PropPath.IsEmpty()) { return {}; }
    if (ObjPath.IsEmpty())  { return PropPath; }
    if (PropPath.IsEmpty()) { return ObjPath; }
    return FString::Printf(TEXT("%s / %s"), *ObjPath, *PropPath);
}

// ── FMCPPropertyPathExtension ─────────────────────────────────────────────────

void FMCPPropertyPathExtension::Register()
{
    UToolMenus* ToolMenus = UToolMenus::Get();
    if (!ToolMenus) { return; }

    UToolMenu* Menu = ToolMenus->ExtendMenu(UE::PropertyEditor::RowContextMenuName);
    if (!Menu) { return; }

    Menu->AddDynamicSection(
        MCPPropertyPath::DynamicSectionName,
        FNewToolMenuDelegate::CreateStatic(&FMCPPropertyPathExtension::FillSection)
    );
}

void FMCPPropertyPathExtension::Unregister()
{
    if (UToolMenus* ToolMenus = UToolMenus::Get())
    {
        if (UToolMenu* Menu = ToolMenus->FindMenu(UE::PropertyEditor::RowContextMenuName))
        {
            Menu->RemoveSection(MCPPropertyPath::DynamicSectionName);
        }
    }
}

void FMCPPropertyPathExtension::FillSection(UToolMenu* InToolMenu)
{
    if (!InToolMenu) { return; }

    const UDetailRowMenuContext* Context = InToolMenu->FindContext<UDetailRowMenuContext>();
    if (!Context || Context->PropertyHandles.IsEmpty()) { return; }

    TSharedPtr<IPropertyHandle> Handle = Context->PropertyHandles[0];

    // If multiple handles share this row (expanded struct), prefer the parent struct handle.
    if (Context->PropertyHandles.Num() > 1)
    {
        if (TSharedPtr<IPropertyHandle> Parent = Handle->GetParentHandle())
        {
            if (const FProperty* ParentProp = Parent->GetProperty())
            {
                if (ParentProp->IsA<FStructProperty>())
                {
                    Handle = Parent;
                }
            }
        }
    }

    if (!Handle.IsValid() || !Handle->IsValidHandle()) { return; }

    const FString FullPath = BuildFullPath(Handle);
    if (FullPath.IsEmpty()) { return; }

    FToolMenuSection& Section = InToolMenu->FindOrAddSection(
        MCPPropertyPath::DynamicSectionName,
        LOCTEXT("SectionLabel", "MCP")
    );

    const FText Tooltip = FText::Format(
        LOCTEXT("CopyPathTooltip", "Copy full property path to clipboard:\n{0}"),
        FText::FromString(FullPath)
    );

    FToolMenuEntry Entry = FToolMenuEntry::InitMenuEntry(
        MCPPropertyPath::EntryName,
        LOCTEXT("CopyPathLabel", "Copy Property Path (MCP)"),
        Tooltip,
        FSlateIcon(FCoreStyle::Get().GetStyleSetName(), "GenericCommands.Copy"),
        FToolUIActionChoice(FUIAction(FExecuteAction::CreateLambda([FullPath]()
        {
            FPlatformApplicationMisc::ClipboardCopy(*FullPath);
        }))),
        EUserInterfaceActionType::Button,
        MCPPropertyPath::EntryName   // TutorialHighlightName → auto FTagMetaData
    );
    Section.AddEntry(Entry);
}

FString FMCPPropertyPathExtension::BuildFullPath(const TSharedPtr<IPropertyHandle>& Handle)
{
    // GeneratePathToProperty() traverses from ObjectItemParent to current node,
    // including array indices, e.g. "Stats.Damage", "Items[2].Name"
    const FString PropPath = Handle->GeneratePathToProperty();

    TArray<UObject*> OuterObjects;
    Handle->GetOuterObjects(OuterObjects);

    FString ObjPath;
    if (!OuterObjects.IsEmpty() && OuterObjects[0] != nullptr)
    {
        // GetPathName() examples:
        //   Blueprint CDO  → /Game/BP_Character.BP_Character_C:Default__BP_Character_C
        //   Scene Actor    → /Game/Maps/TestLevel.TestLevel:PersistentLevel.BP_Character_C_0
        ObjPath = OuterObjects[0]->GetPathName();
    }

    if (ObjPath.IsEmpty() && PropPath.IsEmpty()) { return {}; }
    if (ObjPath.IsEmpty())  { return PropPath; }
    if (PropPath.IsEmpty()) { return ObjPath; }
    return FString::Printf(TEXT("%s / %s"), *ObjPath, *PropPath);
}

void FMCPPropertyPathExtension::AttachDriverIdToWidget(const TSharedRef<SWidget>& Widget, FName TargetTag)
{
    for (const TSharedRef<FTagMetaData>& TagMeta : Widget->GetAllMetaData<FTagMetaData>())
    {
        if (TagMeta->Tag == TargetTag)
        {
            bool bAlreadyHasId = false;
            for (const TSharedRef<FDriverIdMetaData>& IdMeta : Widget->GetAllMetaData<FDriverIdMetaData>())
            {
                if (IdMeta->Id == TargetTag) { bAlreadyHasId = true; break; }
            }
            if (!bAlreadyHasId)
            {
                Widget->AddMetadata<FDriverIdMetaData>(MakeShared<FDriverIdMetaData>(TargetTag));
            }
            return;
        }
    }

    if (FChildren* Children = Widget->GetChildren())
    {
        for (int32 i = 0; i < Children->Num(); ++i)
        {
            AttachDriverIdToWidget(Children->GetChildAt(i), TargetTag);
        }
    }
}

#undef LOCTEXT_NAMESPACE
