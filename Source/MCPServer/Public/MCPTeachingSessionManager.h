// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "MCPTeachingDataFilter.h"
#include "Templates/SharedPointer.h"

class FTransaction;
class SNotificationItem;
class SWindow;
class FBlueprintDifferenceTreeEntry;

/** 示教期间创建的临时对象统一前缀 */
namespace MCPTeachingConstants
{
	/** 快照对象名称前缀 */
	static const TCHAR* SnapshotPrefix = TEXT("MCPTeach_Snapshot_");
	
	/** 其他临时对象前缀（预留） */
	static const TCHAR* TempObjectPrefix = TEXT("MCPTeach_Temp_");
}

/** 单条非事务事件的占位数据 */
struct FMCPTeachingEvent
{
	FMCPTeachingEvent() = default;
	FMCPTeachingEvent(FName InEventName, FString InPayload)
		: EventName(InEventName)
		, Payload(MoveTemp(InPayload))
		, Timestamp(FDateTime::UtcNow())
	{
	}

	FName EventName = NAME_None;
	FString Payload;
	FDateTime Timestamp;
};

/** 属性级差异 */
struct FMCPPropertyDiff
{
	FName PropertyName = NAME_None;
	FString PropertyPath;
	FString OldValue;
	FString NewValue;
	/** 标记属性是否为新增（仅在新对象中存在） */
	bool bIsPropertyAdded = false;
	/** 标记属性是否被删除（仅在旧对象中存在） */
	bool bIsPropertyRemoved = false;
};

/** 对象级差异 */
struct FMCPObjectDiff
{
	FString ObjectPath;
	FString ObjectClass;
	bool bIsObjectAdded = false;
	bool bIsObjectRemoved = false;
	TArray<FMCPPropertyDiff> PropertyDiffs;

	bool HasDifferences() const
	{
		return bIsObjectAdded || bIsObjectRemoved || PropertyDiffs.Num() > 0;
	}
};

/** 事务级差异 */
struct FMCPTransactionDiff
{
	int32 TransactionIndex = INDEX_NONE;
	FString TransactionTitle;
	FString TransactionContext;
	TArray<FMCPObjectDiff> ObjectDiffs;

	bool HasDifferences() const
	{
		for (const FMCPObjectDiff& Diff : ObjectDiffs)
		{
			if (Diff.HasDifferences())
			{
				return true;
			}
		}
		return false;
	}
};

/** 示教整体状态 */
struct FMCPTeachingSessionState
{
	bool bIsRecording = false;
	int32 QueueLengthAtStart = INDEX_NONE;
	TArray<FMCPTeachingEvent> CustomEvents;
	TArray<FMCPTransactionDiff> CapturedDiffs;
};

/**
 * 负责录制/分析示教信息的管理器。
 */
class FMCPTeachingSessionManager : public TSharedFromThis<FMCPTeachingSessionManager>
{
public:
	FMCPTeachingSessionManager();

	/** 开始记录 */
	void StartTeachingSession();

	/** 停止记录并输出 diff */
	void StopTeachingSession();

	/** 是否正在记录 */
	bool IsSessionActive() const { return SessionState.bIsRecording; }

	/** 记录非事务事件（预留接口） */
	void RecordCustomEvent(FName EventName, const FString& Payload);
	void CollectAndApplyFilters();
private:
	void ResetSession();
	void ShowRecordingNotification();
	void HideRecordingNotification(bool bSuccess);

	void CollectDiffsAndDisplay(int32 StartIndex, int32 EndIndex);
	bool RewindEditorTransactions();
	void CaptureTransactionDiff(int32 TransactionIndex, const FTransaction* Transaction);
	void DuplicateSnapshots(const TArray<UObject*>& SourceObjects, TMap<UObject*, UObject*>& OutSnapshots);
	void ReleaseSnapshots(TMap<UObject*, UObject*>& Snapshots);
	FMCPTransactionDiff BuildDiffFromSnapshots(int32 TransactionIndex, const FTransaction* Transaction, const TMap<UObject*, UObject*>& Before, const TMap<UObject*, UObject*>& After);
	void BuildDiffTreeEntries(TArray<TSharedPtr<FBlueprintDifferenceTreeEntry>>& OutEntries);
	void ShowDiffWindow();

	static FString ExportPropertyValue(FProperty* Property, const void* ValuePtr);
	static void CollectPropertyDiffs(UObject* OldObject, UObject* NewObject, TArray<FMCPPropertyDiff>& OutDiffs);

private:
	FMCPTeachingSessionState SessionState;
	TWeakPtr<SNotificationItem> ActiveNotification;
	TWeakPtr<SWindow> DiffResultWindow;
	TSharedPtr<TArray<TSharedPtr<FBlueprintDifferenceTreeEntry>>> CachedTreeEntries;
	FMCPTeachingDataFilterChain FilterChain;
};
