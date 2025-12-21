// Copyright Epic Games, Inc. All Rights Reserved.

#include "MCPTeachingSessionManager.h"

#include "Editor.h"
#include "Editor/Transactor.h"
#include "Framework/Notifications/NotificationManager.h"
#include "DiffUtils.h"
#include "MCPObjectInformDumpLibrary.h"
#include "MCPServer.h"
#include "MCPTeachingDataFilter.h"
#include "Styling/CoreStyle.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/Notifications/SNotificationList.h"
#include "Widgets/SWindow.h"
#include "Framework/Application/SlateApplication.h"
#include "Widgets/Text/STextBlock.h"
#include "Widgets/Input/SMultiLineEditableTextBox.h"
#include "Misc/ITransaction.h"
#include "UObject/UObjectGlobals.h"
#include "Widgets/Layout/SScrollBox.h"

#define LOCTEXT_NAMESPACE "FMCPTeachingSession"

namespace
{
	UTransactor* GetTransBuffer()
	{
		return GEditor ? GEditor->Trans : nullptr;
	}
}

FMCPTeachingSessionManager::FMCPTeachingSessionManager()
{
	CachedTreeEntries = MakeShared<TArray<TSharedPtr<FBlueprintDifferenceTreeEntry>>>();
	ResetSession();
}

void FMCPTeachingSessionManager::StartTeachingSession()
{
	if (!GEditor)
	{
		UE_LOG(LogMCPServer, Error, TEXT("StartTeachingSession: GEditor is null"));
		return;
	}

	ResetSession();
	if (auto TransBuffer = GetTransBuffer())
	{
		SessionState.QueueLengthAtStart = TransBuffer->GetQueueLength();
	}
	SessionState.bIsRecording = true;
	UE_LOG(LogMCPServer, Log, TEXT("Teaching session started. QueueLength=%d"), SessionState.QueueLengthAtStart);
	ShowRecordingNotification();
}

void FMCPTeachingSessionManager::StopTeachingSession()
{
	if (!SessionState.bIsRecording)
	{
		UE_LOG(LogMCPServer, Warning, TEXT("StopTeachingSession: session not active"));
		return;
	}

	SessionState.bIsRecording = false;
	int32 StartIndex = SessionState.QueueLengthAtStart;
	int32 EndIndex = INDEX_NONE;

	if (auto TransBuffer = GetTransBuffer())
	{
		EndIndex = TransBuffer->GetQueueLength() - 1;
	}

	if (StartIndex == INDEX_NONE || EndIndex == INDEX_NONE)
	{
		UE_LOG(LogMCPServer, Warning, TEXT("Stopping teaching session aborted: invalid indices [%d, %d]"), StartIndex, EndIndex);
		HideRecordingNotification(false);
		return;
	}

	if (EndIndex < StartIndex)
	{
		UE_LOG(LogMCPServer, Log, TEXT("Stopping teaching session skipped: no new transactions (start=%d, end=%d)"), StartIndex, EndIndex);
		HideRecordingNotification(true);
		return;
	}

	UE_LOG(LogMCPServer, Log, TEXT("Stopping teaching session. Transactions [%d, %d]"), StartIndex, EndIndex);
	
	// 收集并应用过滤规则
	CollectAndApplyFilters();
	
	CollectDiffsAndDisplay(StartIndex, EndIndex);
	HideRecordingNotification(true);
}

void FMCPTeachingSessionManager::RecordCustomEvent(FName EventName, const FString& Payload)
{
	if (!SessionState.bIsRecording)
	{
		return;
	}

	SessionState.CustomEvents.Emplace(EventName, Payload);
	UE_LOG(LogMCPServer, Verbose, TEXT("Recorded custom event: %s => %s"), *EventName.ToString(), *Payload);
}

void FMCPTeachingSessionManager::ResetSession()
{
	SessionState = FMCPTeachingSessionState();
	SessionState.CustomEvents.Empty();
	SessionState.CapturedDiffs.Empty();
	SessionState.QueueLengthAtStart = INDEX_NONE;

	if (CachedTreeEntries.IsValid())
	{
		CachedTreeEntries->Reset();
	}

	// 清空过滤器链
	FilterChain.ClearFilters();
}

void FMCPTeachingSessionManager::ShowRecordingNotification()
{
	if (ActiveNotification.IsValid())
	{
		ActiveNotification.Pin()->Fadeout();
		ActiveNotification.Reset();
	}

	FNotificationInfo Info(LOCTEXT("TeachingSessionRecording", "示教进行中..."));
	Info.bUseLargeFont = true;
	Info.bFireAndForget = false;
	Info.FadeOutDuration = 1.0f;
	Info.ExpireDuration = 0.0f;
	Info.CheckBoxState = ECheckBoxState::Checked;
	Info.bUseSuccessFailIcons = false;
	Info.Image = FCoreStyle::Get().GetBrush(TEXT("Icons.Record"));

	ActiveNotification = FSlateNotificationManager::Get().AddNotification(Info);
	if (ActiveNotification.IsValid())
	{
		ActiveNotification.Pin()->SetCompletionState(SNotificationItem::CS_Pending);
	}
}

void FMCPTeachingSessionManager::HideRecordingNotification(bool bSuccess)
{
	if (ActiveNotification.IsValid())
	{
		ActiveNotification.Pin()->SetText(LOCTEXT("TeachingSessionFinished", "示教已结束"));
		ActiveNotification.Pin()->SetCompletionState(bSuccess ? SNotificationItem::CS_Success : SNotificationItem::CS_Fail);
		ActiveNotification.Pin()->Fadeout();
		ActiveNotification.Reset();
	}
}

void FMCPTeachingSessionManager::CollectDiffsAndDisplay(int32 StartIndex, int32 EndIndex)
{
	if (!GetTransBuffer() || StartIndex == INDEX_NONE || EndIndex == INDEX_NONE || StartIndex > EndIndex)
	{
		UE_LOG(LogMCPServer, Warning, TEXT("CollectDiffsAndDisplay: invalid range [%d, %d]"), StartIndex, EndIndex);
		return;
	}

	if (!RewindEditorTransactions())
	{
		UE_LOG(LogMCPServer, Error, TEXT("CollectDiffsAndDisplay: failed to rewind transactions"));
		return;
	}

	SessionState.CapturedDiffs.Reset();

	for (int32 TxIndex = 0; TxIndex <= EndIndex; ++TxIndex)
	{
		const FTransaction* Transaction = GetTransBuffer()->GetTransaction(TxIndex);
		if (!Transaction)
		{
			UE_LOG(LogMCPServer, Warning, TEXT("Transaction %d is null"), TxIndex);
			continue;
		}

		const bool bShouldCapture = TxIndex >= StartIndex;
		TArray<UObject*> TransactionObjects;
		Transaction->GetTransactionObjects(TransactionObjects);

		TMap<UObject*, UObject*> SnapshotsBefore;
		DuplicateSnapshots(TransactionObjects, SnapshotsBefore);

		if (!GEditor->RedoTransaction())
		{
			UE_LOG(LogMCPServer, Error, TEXT("RedoTransaction failed at %d"), TxIndex);
			ReleaseSnapshots(SnapshotsBefore);
			continue;
		}

		TMap<UObject*, UObject*> SnapshotsAfter;
		DuplicateSnapshots(TransactionObjects, SnapshotsAfter);

		if (bShouldCapture)
		{
			CaptureTransactionDiff(TxIndex, Transaction);
			FMCPTransactionDiff Diff = BuildDiffFromSnapshots(TxIndex, Transaction, SnapshotsBefore, SnapshotsAfter);
			if (Diff.HasDifferences())
			{
				SessionState.CapturedDiffs.Add(MoveTemp(Diff));
			}
		}

		ReleaseSnapshots(SnapshotsBefore);
		ReleaseSnapshots(SnapshotsAfter);
	}

	// 应用过滤器链到收集的差异数据
	UE_LOG(LogMCPServer, Log, TEXT("Applying filters to %d captured diffs"), SessionState.CapturedDiffs.Num());
	FilterChain.ApplyFilters(SessionState.CapturedDiffs);
	UE_LOG(LogMCPServer, Log, TEXT("After filtering: %d diffs remaining"), SessionState.CapturedDiffs.Num());

	ShowDiffWindow();
}

bool FMCPTeachingSessionManager::RewindEditorTransactions()
{
	if (!GEditor)
	{
		return false;
	}

	auto TransBuffer = GetTransBuffer();
	if (!TransBuffer)
	{
		return false;
	}

	const int32 QueueLength = TransBuffer->GetQueueLength();
	for (int32 i = 0; i < QueueLength; ++i)
	{
		if (!GEditor->UndoTransaction())
		{
			UE_LOG(LogMCPServer, Warning, TEXT("Failed to undo transaction %d / %d"), i, QueueLength);
			return false;
		}
	}

	return true;
}

void FMCPTeachingSessionManager::CaptureTransactionDiff(int32 TransactionIndex, const FTransaction* Transaction)
{
	UE_LOG(LogMCPServer, Log, TEXT("Analyzing transaction %d: %s"), TransactionIndex, *Transaction->GetTitle().ToString());
}

void FMCPTeachingSessionManager::DuplicateSnapshots(const TArray<UObject*>& SourceObjects, TMap<UObject*, UObject*>& OutSnapshots)
{
	OutSnapshots.Empty();
	static int32 SnapshotCounter = 0;
	UPackage* SnapshotOuter = GetTransientPackage();
	
	for (UObject* Obj : SourceObjects)
	{
		if (!IsValid(Obj))
		{
			continue;
		}

		// 某些对象类型可能不支持复制，需要跳过
		if (Obj->HasAnyFlags(RF_ClassDefaultObject | RF_ArchetypeObject))
		{
			UE_LOG(LogMCPServer, Verbose, TEXT("Skipping snapshot for CDO/Archetype: %s"),*GetNameSafe(Obj));
			continue;
		}

		const FName SnapshotName = MakeUniqueObjectName(
			SnapshotOuter,
			Obj->GetClass(),
			FName(*FString::Printf(TEXT("%s%s_%d"), MCPTeachingConstants::SnapshotPrefix,*GetNameSafe(Obj), SnapshotCounter++)));

		FObjectDuplicationParameters Params(Obj, SnapshotOuter);
		Params.DestName = SnapshotName;
		// 设置 Transient 标志，但同时添加 Standalone 防止被 GC
		Params.ApplyFlags |= RF_Transient | RF_Standalone;
		// 确保不复制某些不应该复制的标志
		Params.FlagMask &= ~(RF_ArchetypeObject | RF_ClassDefaultObject);

		UObject* Snapshot = StaticDuplicateObjectEx(Params);
		
		// 验证快照对象的有效性
		if (!ensureAlways(Snapshot != nullptr))
		{
			UE_LOG(LogMCPServer, Error, TEXT("StaticDuplicateObjectEx returned nullptr for object: %s"),*GetNameSafe(Obj));
			continue;
		}
		
		if (!ensureAlways(IsValid(Snapshot)))
		{
			UE_LOG(LogMCPServer, Error, TEXT("StaticDuplicateObjectEx created invalid snapshot for object: %s"),*GetNameSafe(Obj));
			continue;
		}

		// 再次验证快照对象的类是否正确
		if (!ensureAlways(Snapshot->GetClass() == Obj->GetClass()))
		{
			UE_LOG(LogMCPServer, Error, TEXT("Snapshot class mismatch for object: %s (Expected: %s, Got: %s)"), 
				*Obj->GetName(), 
				*Obj->GetClass()->GetName(), 
				*Snapshot->GetClass()->GetName());
			continue;
		}

		OutSnapshots.Add(Obj, Snapshot);
	}
}

void FMCPTeachingSessionManager::ReleaseSnapshots(TMap<UObject*, UObject*>& Snapshots)
{
	for (TPair<UObject*, UObject*>& Pair : Snapshots)
	{
		if (Pair.Value && IsValid(Pair.Value))
		{
			// 移除 Standalone 标志，允许 GC 回收
			Pair.Value->ClearFlags(RF_Standalone);
			
#if ENGINE_MAJOR_VERSION >= 5
			Pair.Value->MarkAsGarbage();
#else
			Pair.Value->MarkPendingKill();
#endif
			
			UE_LOG(LogMCPServer, Verbose, TEXT("Released snapshot: %s"), *Pair.Value->GetName());
		}
	}
	Snapshots.Empty();
}

FMCPTransactionDiff FMCPTeachingSessionManager::BuildDiffFromSnapshots(int32 TransactionIndex, const FTransaction* Transaction, const TMap<UObject*, UObject*>& Before, const TMap<UObject*, UObject*>& After)
{
	FMCPTransactionDiff Result;
	Result.TransactionIndex = TransactionIndex;
	Result.TransactionTitle = Transaction->GetTitle().ToString();

	const FTransactionContext TransactionContext = Transaction->GetContext();
	Result.TransactionContext = TransactionContext.Context;

	for (const TPair<UObject*, UObject*>& PairBefore : Before)
	{
		UObject* OriginalObj = PairBefore.Key;
		UObject* OldSnapshot = PairBefore.Value;
		
		// 验证旧快照的有效性
		if (!ensureAlways(IsValid(OldSnapshot)))
		{
			UE_LOG(LogMCPServer, Error, TEXT("BuildDiffFromSnapshots: Invalid OldSnapshot for object %s"), 
				OriginalObj ? *OriginalObj->GetName() : TEXT("<null>"));
			continue;
		}
		
		UObject* const* NewSnapshotPtr = After.Find(OriginalObj);

		FMCPObjectDiff ObjectDiff;
		ObjectDiff.ObjectPath = OriginalObj ? OriginalObj->GetPathName() : TEXT("<null>");
		ObjectDiff.ObjectClass = OriginalObj ? OriginalObj->GetClass()->GetName() : TEXT("Unknown");

		if (!NewSnapshotPtr)
		{
			ObjectDiff.bIsObjectRemoved = true;
		}
		else
		{
			// 验证新快照的有效性
			if (!ensureAlways(IsValid(*NewSnapshotPtr)))
			{
				UE_LOG(LogMCPServer, Error, TEXT("BuildDiffFromSnapshots: Invalid NewSnapshot for object %s"), 
					OriginalObj ? *OriginalObj->GetName() : TEXT("<null>"));
				continue;
			}
			
			CollectPropertyDiffs(OldSnapshot, *NewSnapshotPtr, ObjectDiff.PropertyDiffs);
		}

		if (ObjectDiff.HasDifferences())
		{
			Result.ObjectDiffs.Add(MoveTemp(ObjectDiff));
		}
	}

	for (const TPair<UObject*, UObject*>& PairAfter : After)
	{
		if (!Before.Contains(PairAfter.Key))
		{
			FMCPObjectDiff ObjectDiff;
			ObjectDiff.ObjectPath = PairAfter.Key ? PairAfter.Key->GetPathName() : TEXT("<null>");
			ObjectDiff.ObjectClass = PairAfter.Key ? PairAfter.Key->GetClass()->GetName() : TEXT("Unknown");
			ObjectDiff.bIsObjectAdded = true;
			Result.ObjectDiffs.Add(MoveTemp(ObjectDiff));
		}
	}

	return Result;
}

FString FMCPTeachingSessionManager::ExportPropertyValue(FProperty* Property, const void* ValuePtr)
{
	return UMCPObjectInformDumpLibrary::ExportPropertyValueToText(Property, ValuePtr, false, false, nullptr);
}

void FMCPTeachingSessionManager::CollectPropertyDiffs(UObject* OldObject, UObject* NewObject, TArray<FMCPPropertyDiff>& OutDiffs)
{
	// 验证对象有效性，防止使用已被 GC 或损坏的对象
	if (!ensureAlways(IsValid(OldObject)))
	{
		UE_LOG(LogMCPServer, Error, TEXT("CollectPropertyDiffs: Invalid OldObject passed"));
		return;
	}
	
	if (!ensureAlways(IsValid(NewObject)))
	{
		UE_LOG(LogMCPServer, Error, TEXT("CollectPropertyDiffs: Invalid NewObject passed"));
		return;
	}

	// 允许不同类的对象比较，以支持类结构变化的场景
	UClass* OldClass = OldObject->GetClass();
	UClass* NewClass = NewObject->GetClass();

	// 收集旧对象的所有属性到 Map 中
	TMap<FName, FProperty*> OldProperties;
	for (TFieldIterator<FProperty> PropIt(OldClass); PropIt; ++PropIt)
	{
		FProperty* Property = *PropIt;
		OldProperties.Add(Property->GetFName(), Property);
	}

	// 收集新对象的所有属性到 Map 中
	TMap<FName, FProperty*> NewProperties;
	for (TFieldIterator<FProperty> PropIt(NewClass); PropIt; ++PropIt)
	{
		FProperty* Property = *PropIt;
		NewProperties.Add(Property->GetFName(), Property);
	}

	// 检测属性值变化和删除的属性
	for (const TPair<FName, FProperty*>& OldPair : OldProperties)
	{
		FName PropertyName = OldPair.Key;
		FProperty* OldProperty = OldPair.Value;
		FProperty** NewPropertyPtr = NewProperties.Find(PropertyName);

		if (!NewPropertyPtr)
		{
			// 属性在新对象中不存在 - 标记为删除
			FMCPPropertyDiff Diff;
			Diff.PropertyName = PropertyName;
			Diff.PropertyPath = OldProperty->GetNameCPP();
			const void* OldValuePtr = OldProperty->ContainerPtrToValuePtr<void>(OldObject);
			Diff.OldValue = OldValuePtr ? ExportPropertyValue(OldProperty, OldValuePtr) : TEXT("<null>");
			Diff.NewValue = TEXT("<removed>");
			Diff.bIsPropertyRemoved = true;
			OutDiffs.Add(MoveTemp(Diff));
		}
		else
		{
			// 属性在两个对象中都存在 - 检查值是否变化
			FProperty* NewProperty = *NewPropertyPtr;
			const void* OldValuePtr = OldProperty->ContainerPtrToValuePtr<void>(OldObject);
			const void* NewValuePtr = NewProperty->ContainerPtrToValuePtr<void>(NewObject);

			if (!OldValuePtr || !NewValuePtr)
			{
				continue;
			}

			// 检查属性类型是否一致
			if (OldProperty->GetClass() != NewProperty->GetClass())
			{
				// 属性类型变化，记录为变化
				FMCPPropertyDiff Diff;
				Diff.PropertyName = PropertyName;
				Diff.PropertyPath = OldProperty->GetNameCPP();
				Diff.OldValue = FString::Printf(TEXT("%s (type: %s)"), *ExportPropertyValue(OldProperty, OldValuePtr), *OldProperty->GetClass()->GetName());
				Diff.NewValue = FString::Printf(TEXT("%s (type: %s)"), *ExportPropertyValue(NewProperty, NewValuePtr), *NewProperty->GetClass()->GetName());
				OutDiffs.Add(MoveTemp(Diff));
				continue;
			}

		// 对于指针类型的属性，只比对其 PathName 是否相等
		bool bIsDifferent = false;
		if (FObjectProperty* ObjProperty = CastField<FObjectProperty>(OldProperty))
		{
			// 对象指针类型：比对 PathName
			UObject* OldObj = ObjProperty->GetObjectPropertyValue(OldValuePtr);
			UObject* NewObj = ObjProperty->GetObjectPropertyValue(NewValuePtr);
			
			// 如果一个为空一个不为空，或者两者的 PathName 不同，则认为有差异
			if ((OldObj == nullptr) != (NewObj == nullptr))
			{
				bIsDifferent = true;
			}
			else if (OldObj && NewObj)
			{
				// bIsDifferent = (OldObj->GetPathName() != NewObj->GetPathName());
				bIsDifferent = (OldObj->GetClass() != NewObj->GetClass());
			}
		}
		else if (FWeakObjectProperty* WeakObjProperty = CastField<FWeakObjectProperty>(OldProperty))
		{
			// 弱对象指针类型：比对 PathName
			FWeakObjectPtr OldWeakPtr = WeakObjProperty->GetPropertyValue(OldValuePtr);
			FWeakObjectPtr NewWeakPtr = WeakObjProperty->GetPropertyValue(NewValuePtr);
			UObject* OldObj = OldWeakPtr.Get();
			UObject* NewObj = NewWeakPtr.Get();
			
			if ((OldObj == nullptr) != (NewObj == nullptr))
			{
				bIsDifferent = true;
			}
			else if (OldObj && NewObj)
			{
				bIsDifferent = (OldObj->GetPathName() != NewObj->GetPathName());
			}
		}
		else if (FSoftObjectProperty* SoftObjProperty = CastField<FSoftObjectProperty>(OldProperty))
		{
			// 软对象指针类型：比对 PathName
			FSoftObjectPtr OldSoftPtr = SoftObjProperty->GetPropertyValue(OldValuePtr);
			FSoftObjectPtr NewSoftPtr = SoftObjProperty->GetPropertyValue(NewValuePtr);
			
			bIsDifferent = (OldSoftPtr.ToSoftObjectPath() != NewSoftPtr.ToSoftObjectPath());
		}
		else
		{
			// 其他类型：使用默认的 Identical 比对
			bIsDifferent = !OldProperty->Identical(OldValuePtr, NewValuePtr);
		}
		
		if (bIsDifferent)
		{
			// 属性值发生变化
			FMCPPropertyDiff Diff;
			Diff.PropertyName = PropertyName;
			Diff.PropertyPath = OldProperty->GetNameCPP();
			Diff.OldValue = ExportPropertyValue(OldProperty, OldValuePtr);
			Diff.NewValue = ExportPropertyValue(NewProperty, NewValuePtr);
			OutDiffs.Add(MoveTemp(Diff));
		}
		}
	}

	// 检测新增的属性
	for (const TPair<FName, FProperty*>& NewPair : NewProperties)
	{
		FName PropertyName = NewPair.Key;
		FProperty* NewProperty = NewPair.Value;

		if (!OldProperties.Contains(PropertyName))
		{
			// 属性在旧对象中不存在 - 标记为新增
			FMCPPropertyDiff Diff;
			Diff.PropertyName = PropertyName;
			Diff.PropertyPath = NewProperty->GetNameCPP();
			Diff.OldValue = TEXT("<added>");
			const void* NewValuePtr = NewProperty->ContainerPtrToValuePtr<void>(NewObject);
			Diff.NewValue = NewValuePtr ? ExportPropertyValue(NewProperty, NewValuePtr) : TEXT("<null>");
			Diff.bIsPropertyAdded = true;
			OutDiffs.Add(MoveTemp(Diff));
		}
	}
}

void FMCPTeachingSessionManager::BuildDiffTreeEntries(TArray<TSharedPtr<FBlueprintDifferenceTreeEntry>>& OutEntries)
{
	OutEntries.Empty();
	for (const FMCPTransactionDiff& TxDiff : SessionState.CapturedDiffs)
	{
		if (!TxDiff.HasDifferences())
		{
			continue;
		}

		const FText TxLabel = FText::Format(LOCTEXT("TransactionLabel", "事务 {0}: {1}"), TxDiff.TransactionIndex, FText::FromString(TxDiff.TransactionTitle));
		TArray<TSharedPtr<FBlueprintDifferenceTreeEntry>> ObjectEntries;

		for (const FMCPObjectDiff& ObjDiff : TxDiff.ObjectDiffs)
		{
			const FText ObjLabel = FText::FromString(FString::Printf(TEXT("%s (%s)"), *ObjDiff.ObjectPath, *ObjDiff.ObjectClass));
			TArray<TSharedPtr<FBlueprintDifferenceTreeEntry>> PropertyEntries;

			for (const FMCPPropertyDiff& PropDiff : ObjDiff.PropertyDiffs)
			{
				FText PropLabel;
				if (PropDiff.bIsPropertyAdded)
				{
					PropLabel = FText::Format(LOCTEXT("PropertyAddedLabel", "属性 {0} [新增]"), FText::FromName(PropDiff.PropertyName));
				}
				else if (PropDiff.bIsPropertyRemoved)
				{
					PropLabel = FText::Format(LOCTEXT("PropertyRemovedLabel", "属性 {0} [删除]"), FText::FromName(PropDiff.PropertyName));
				}
				else
				{
					PropLabel = FText::Format(LOCTEXT("PropertyDiffLabel", "属性 {0}"), FText::FromName(PropDiff.PropertyName));
				}

				TSharedPtr<FBlueprintDifferenceTreeEntry> PropEntry = MakeShared<FBlueprintDifferenceTreeEntry>(
					FOnDiffEntryFocused(),
					FGenerateDiffEntryWidget::CreateLambda([PropDiff, PropLabel]()
					{
						TSharedRef<SVerticalBox> ContentBox = SNew(SVerticalBox);

						// 显示属性名称标题（使用 PropLabel 包含状态信息）
						ContentBox->AddSlot().AutoHeight().Padding(0, 0, 0, 8)
						[
							SNew(STextBlock)
								.Text(PropLabel)
								.Font(FCoreStyle::GetDefaultFontStyle("Bold", 11))
								.ColorAndOpacity(PropDiff.bIsPropertyAdded ? FLinearColor::Green : 
								                 PropDiff.bIsPropertyRemoved ? FLinearColor::Red : 
								                 FLinearColor::White)
						];

						if (PropDiff.bIsPropertyAdded)
						{
							// 新增属性 - 显示新值
							ContentBox->AddSlot().MaxHeight(200.0f)
							[
								SNew(SScrollBox)
								+ SScrollBox::Slot()
								[
									SNew(SMultiLineEditableTextBox)
										.Text(FText::FromString(FString::Printf(TEXT("值: %s"), *PropDiff.NewValue)))
										.IsReadOnly(true)
										.AutoWrapText(true)
								]
							];
						}
						else if (PropDiff.bIsPropertyRemoved)
						{
							// 删除属性 - 显示旧值
							ContentBox->AddSlot().MaxHeight(200.0f)
							[
								SNew(SScrollBox)
								+ SScrollBox::Slot()
								[
									SNew(SMultiLineEditableTextBox)
										.Text(FText::FromString(FString::Printf(TEXT("原值: %s"), *PropDiff.OldValue)))
										.IsReadOnly(true)
										.AutoWrapText(true)
								]
							];
						}
						else
						{
							// 属性值变化 - 显示旧值和新值
							ContentBox->AddSlot().MaxHeight(150.0f).Padding(0, 0, 0, 4)
							[
								SNew(SScrollBox)
								+ SScrollBox::Slot()
								[
									SNew(SMultiLineEditableTextBox)
										.Text(FText::FromString(FString::Printf(TEXT("旧值: %s"), *PropDiff.OldValue)))
										.IsReadOnly(true)
										.AutoWrapText(true)
								]
							];
							ContentBox->AddSlot().MaxHeight(150.0f)
							[
								SNew(SScrollBox)
								+ SScrollBox::Slot()
								[
									SNew(SMultiLineEditableTextBox)
										.Text(FText::FromString(FString::Printf(TEXT("新值: %s"), *PropDiff.NewValue)))
										.IsReadOnly(true)
										.AutoWrapText(true)
								]
							];
						}

						return SNew(SBox)
							.Padding(FMargin(4.f))
							[
								SNew(SBorder)
								.Padding(4)
								[ 
									ContentBox
								]
							];
					})
				);
				PropertyEntries.Add(PropEntry);
			}

			if (ObjDiff.bIsObjectAdded)
			{
				TSharedPtr<FBlueprintDifferenceTreeEntry> AddedEntry = MakeShared<FBlueprintDifferenceTreeEntry>(
					FOnDiffEntryFocused(),
					FGenerateDiffEntryWidget::CreateLambda([ObjDiff]()
					{
						return SNew(STextBlock).Text(LOCTEXT("ObjectAdded", "对象新增"));
					})
				);
				PropertyEntries.Add(AddedEntry);
			}

			if (ObjDiff.bIsObjectRemoved)
			{
				TSharedPtr<FBlueprintDifferenceTreeEntry> RemovedEntry = MakeShared<FBlueprintDifferenceTreeEntry>(
					FOnDiffEntryFocused(),
					FGenerateDiffEntryWidget::CreateLambda([ObjDiff]()
					{
						return SNew(STextBlock).Text(LOCTEXT("ObjectRemoved", "对象被移除"));
					})
				);
				PropertyEntries.Add(RemovedEntry);
			}

			if (PropertyEntries.Num() == 0)
			{
				continue;
			}

			TSharedPtr<FBlueprintDifferenceTreeEntry> ObjEntry = FBlueprintDifferenceTreeEntry::CreateCategoryEntry(
				ObjLabel,
				FText::FromString(ObjDiff.ObjectPath),
				FOnDiffEntryFocused(),
				PropertyEntries,
				true);

			ObjectEntries.Add(ObjEntry);
		}

		if (ObjectEntries.Num() == 0)
		{
			continue;
		}

		TSharedPtr<FBlueprintDifferenceTreeEntry> TxEntry = FBlueprintDifferenceTreeEntry::CreateCategoryEntry(
			TxLabel,
			FText::FromString(TxDiff.TransactionContext),
			FOnDiffEntryFocused(),
			ObjectEntries,
			true);

		OutEntries.Add(TxEntry);
	}

	if (OutEntries.Num() == 0)
	{
		OutEntries.Add(FBlueprintDifferenceTreeEntry::NoDifferencesEntry());
	}
}

void FMCPTeachingSessionManager::ShowDiffWindow()
{
	if (!CachedTreeEntries.IsValid())
	{
		CachedTreeEntries = MakeShared<TArray<TSharedPtr<FBlueprintDifferenceTreeEntry>>>();
	}

	BuildDiffTreeEntries(*CachedTreeEntries);

	if (CachedTreeEntries->Num() == 0)
	{
		UE_LOG(LogMCPServer, Log, TEXT("No differences captured during teaching session"));
		return;
	}

	TSharedRef<SVerticalBox> RootWidget = SNew(SVerticalBox)
	+ SVerticalBox::Slot().AutoHeight()
	[
		SNew(STextBlock)
			.Text(LOCTEXT("TeachingDiffTitle", "示教期间的修改"))
			.Font(FCoreStyle::GetDefaultFontStyle("Bold", 14))
	]
	+ SVerticalBox::Slot().FillHeight(1.0f)
	[
		DiffTreeView::CreateTreeView(CachedTreeEntries.Get())
	];

	TSharedRef<SWindow> Window = SNew(SWindow)
		.Title(LOCTEXT("TeachingDiffWindowTitle", "示教 Diff"))
		.ClientSize(FVector2D(600.f, 400.f))
		.SupportsMinimize(true)
		.SupportsMaximize(true)
		[RootWidget];

	FSlateApplication::Get().AddWindow(Window);
	DiffResultWindow = Window;
}

void FMCPTeachingSessionManager::CollectAndApplyFilters()
{
	// 这里是收集过滤规则的地方
	// 子类或外部代码可以在停止示教前通过GetFilterChain()添加过滤器
	// 例如：
	// GetFilterChain().AddFilter(MakeShared<FMyCustomFilter>());
	
	// 添加默认的过滤器
	// 1. 过滤掉UBlueprint资源对象的差异，只保留蓝图实例对象的变化
	FilterChain.AddFilter(MakeShared<FMCPBlueprintObjectFilter>());
	
	// 2. 只保留蓝图中可编辑的属性变化，过滤掉只读属性（如VisibleAnywhere、BlueprintReadOnly等）
	FilterChain.AddFilter(MakeShared<FMCPBlueprintVisiblePropertyFilter>());
	
	UE_LOG(LogMCPServer, Log, TEXT("CollectAndApplyFilters: %d filters registered"), FilterChain.GetFilterCount());
	
	// 注意：实际的过滤应用会在CollectDiffsAndDisplay中进行
}

#undef LOCTEXT_NAMESPACE