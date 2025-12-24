// Copyright Epic Games, Inc. All Rights Reserved.

#include "MCPEditorLibrary.h"
#include "GameplayTagsManager.h"
#include "GameplayTagsSettings.h"
#include "MCPServer.h"

bool UMCPEditorLibrary::CreateGameplayTag(const FString& TagName)
{
	if (TagName.IsEmpty())
	{
		UE_LOG(LogMCPServer, Warning, TEXT("CreateGameplayTag: TagName is empty"));
		return false;
	}

	// Check if tag already exists
	if (DoesGameplayTagExist(TagName))
	{
		UE_LOG(LogMCPServer, Warning, TEXT("CreateGameplayTag: Tag '%s' already exists"), *TagName);
		return false;
	}

	// Get the GameplayTagsManager
	UGameplayTagsManager& TagManager = UGameplayTagsManager::Get();
	
	// Get the GameplayTagsSettings
	UGameplayTagsSettings* Settings = GetMutableDefault<UGameplayTagsSettings>();
	if (!Settings)
	{
		UE_LOG(LogMCPServer, Error, TEXT("CreateGameplayTag: Failed to get GameplayTagsSettings"));
		return false;
	}

	// Create a new tag entry
	FGameplayTagTableRow NewTag;
	NewTag.Tag = FName(*TagName);
	NewTag.DevComment = TEXT("");

	// Add the tag to the settings
	Settings->GameplayTagList.Add(NewTag);
	
	// Mark the settings as modified and save
	Settings->MarkPackageDirty();
	Settings->SaveConfig();

	// Request the manager to reconstruct the tag tree
	TagManager.EditorRefreshGameplayTagTree();

	UE_LOG(LogMCPServer, Log, TEXT("CreateGameplayTag: Successfully created tag '%s'"), *TagName);
	return true;
}

bool UMCPEditorLibrary::DoesGameplayTagExist(const FString& TagName)
{
	if (TagName.IsEmpty())
	{
		return false;
	}

	// Get the GameplayTagsManager
	UGameplayTagsManager& TagManager = UGameplayTagsManager::Get();
	
	// Try to find the tag
	FGameplayTag Tag = TagManager.RequestGameplayTag(FName(*TagName), false);
	
	// If the tag is valid, it exists
	return Tag.IsValid();
}
