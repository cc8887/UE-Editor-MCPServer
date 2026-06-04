// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "MCPPropertyPathLibrary.generated.h"

class IPropertyHandle;

/**
 * Adds "Copy Property Path (MCP)" to the Details Panel row right-click menu.
 * The copied string format:  {ObjectPath} / {PropertyPath}
 * e.g.  /Game/BP_Character.BP_Character_C:Default__BP_Character_C / Stats.Damage
 *
 * The menu item is registered on module startup and unregistered on shutdown.
 * Blueprint-callable helpers let tests retrieve the same string programmatically.
 */
UCLASS()
class MCPSERVER_API UMCPPropertyPathLibrary : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()

public:
    /**
     * Build the combined "{ObjectPath} / {PropertyPath}" string for a given
     * UObject and a dot-separated property path.
     *
     * @param Object    The object whose path is used as the prefix.
     * @param PropPath  Dot-path to the property, e.g. "Stats.Damage".
     */
    UFUNCTION(BlueprintCallable, Category = "MCP|Editor|PropertyPath",
        meta = (DisplayName = "Build Property Path"))
    static FString BuildPropertyPath(UObject* Object, const FString& PropPath);
};

// ── Internal: Details Panel context-menu extension ───────────────────────────

class FMCPPropertyPathExtension
{
public:
    static void Register();
    static void Unregister();

private:
    static void FillSection(UToolMenu* InToolMenu);
    static FString BuildFullPath(const TSharedPtr<IPropertyHandle>& Handle);

    /**
     * Recursively walk the widget tree and attach FDriverIdMetaData to any
     * widget that already carries a matching FTagMetaData(TargetTag),
     * enabling Automation Driver By::Id() lookup.
     */
    static void AttachDriverIdToWidget(const TSharedRef<SWidget>& Widget, FName TargetTag);
};
