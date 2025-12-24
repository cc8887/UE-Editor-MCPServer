// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "GameplayTagContainer.h"
#include "MCPEditorLibrary.generated.h"

/**
 * Blueprint function library for editor helper operations
 */
UCLASS()
class MCPSERVER_API UMCPEditorLibrary : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	/**
	 * Create a new GameplayTag and add it to the project settings
	 * @param TagName The name of the tag to create (e.g., "Ability.Test.NewTag")
	 * @return True if the tag was created successfully, false otherwise
	 */
	UFUNCTION(BlueprintCallable, Category = "MCP|Editor|GameplayTag", meta = (DisplayName = "Create Gameplay Tag"))
	static bool CreateGameplayTag(const FString& TagName);

	/**
	 * Check if a GameplayTag exists in the project
	 * @param TagName The name of the tag to check
	 * @return True if the tag exists, false otherwise
	 */
	UFUNCTION(BlueprintPure, Category = "MCP|Editor|GameplayTag", meta = (DisplayName = "Does Gameplay Tag Exist"))
	static bool DoesGameplayTagExist(const FString& TagName);
};
