#include <memory>
#include <string>

#include "neurosis/utils.h"
#include "neurosis/parser_state.h"
#include "neurosis/parser_transitions.h"
#include "neurosis/populate_test_inputs.h"
#include "neurosis/sentence.proto.h"
#include "task_context.h"
#include "task_spec.proto.h"
#include "term_frequency_map.h"
#include "testing/base/public/googletest.h"
#include "testing/base/public/gunit.h"
#include "tensorflow/core/lib/core/status.h"
#include "tensorflow/core/platform/env.h"

namespace neurosis {

class TaggerTransitionTest : public ::testing::Test {
 public:
  TaggerTransitionTest()
      : transition_system_(ParserTransitionSystem::Create("tagger")) {}

 protected:
  // Creates a label map and a tag map for testing based on the given
  // document and initializes the transition system appropriately.
  void SetUpForDocument(const Sentence &document) {
    input_label_map_ = context_.GetInput("label-map", "text", "");
    input_label_map_ = context_.GetInput("tag-map", "text", "");
    transition_system_->Setup(&context_);
    PopulateTestInputs::Defaults(document).Populate(&context_);
    label_map_.Load(TaskContext::InputFile(*input_label_map_),
                    0 /* minimum frequency */,
                    -1 /* maximum number of terms */);
    transition_system_->Init(&context_);
  }

  // Creates a cloned state from a sentence in order to test that cloning
  // works correctly for the new parser states.
  ParserState *NewClonedState(Sentence *sentence) {
    ParserState state(sentence, transition_system_->NewTransitionState(
                                    true /* training mode */),
                      &label_map_);
    return state.Clone();
  }

  // Performs gold transitions and check that the labels and heads recorded
  // in the parser state match gold heads and labels.
  void GoldParse(Sentence *sentence) {
    ParserState *state = NewClonedState(sentence);
    LOG(INFO) << "Initial parser state: " << state->ToString();
    while (!transition_system_->IsFinalState(*state)) {
      ParserAction action = transition_system_->GetNextGoldAction(*state);
      EXPECT_TRUE(transition_system_->IsAllowedAction(action, *state));
      LOG(INFO) << "Performing action: "
                << transition_system_->ActionAsString(action, *state);
      transition_system_->PerformActionWithoutHistory(action, state);
      LOG(INFO) << "Parser state: " << state->ToString();
    }
    delete state;
  }

  // Always takes the default action, and verifies that this leads to
  // a final state through a sequence of allowed actions.
  void DefaultParse(Sentence *sentence) {
    ParserState *state = NewClonedState(sentence);
    LOG(INFO) << "Initial parser state: " << state->ToString();
    while (!transition_system_->IsFinalState(*state)) {
      ParserAction action = transition_system_->GetDefaultAction(*state);
      EXPECT_TRUE(transition_system_->IsAllowedAction(action, *state));
      LOG(INFO) << "Performing action: "
                << transition_system_->ActionAsString(action, *state);
      transition_system_->PerformActionWithoutHistory(action, state);
      LOG(INFO) << "Parser state: " << state->ToString();
    }
    delete state;
  }

  TaskContext context_;
  TaskInput *input_label_map_ = nullptr;
  TermFrequencyMap label_map_;
  std::unique_ptr<ParserTransitionSystem> transition_system_;
};

TEST_F(TaggerTransitionTest, SingleSentenceDocumentTest) {
  string document_text;
  Sentence document;
  TF_CHECK_OK(ReadFileToString(tensorflow::Env::Default(),
                               FLAGS_test_srcdir +
                                   "/google3/nlp/saft/components/dependencies/"
                                   "opensource/testdata/document",
                               &document_text));
  LOG(INFO) << "see doc\n:" << document_text;
  CHECK(document.ParseASCII(document_text));
  SetUpForDocument(document);
  GoldParse(&document);
  DefaultParse(&document);
}

}  // namespace neurosis
